import hashlib
import json
import re
import secrets
import sqlite3
from functools import lru_cache
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from .config import settings

app = FastAPI(title="Replatform / GreenU authentication PoC", version="0.1.0")
bearer = HTTPBearer()
GRANT = "urn:greenai:params:oauth:grant-type:qr"


def device(x_rvm_api_key: Annotated[str, Header()]):
    if not secrets.compare_digest(x_rvm_api_key, settings().rvm_api_key.get_secret_value()):
        raise HTTPException(401, "Invalid device credentials")


@lru_cache
def jwks():
    return jwt.PyJWKClient(settings().jwks_url, timeout=5, lifespan=60)


def claims(credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)]):
    try:
        key = jwks().get_signing_key_from_jwt(credentials.credentials)
        data = jwt.decode(credentials.credentials, key.key, algorithms=["RS256"],
                          issuer=settings().keycloak_issuer, audience="replatform-api",
                          options={"require": ["exp", "iat", "sub", "iss", "aud"]})
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, "Identity verification temporarily unavailable") from None
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token") from None
    if (data.get("azp") != "rvm-auth-backend" or data.get("tenant") != "hku"
            or data.get("identity_provider") != "greenu"
            or not re.fullmatch(r"[A-Za-z0-9-]{1,36}", data.get("external_member_id", ""))):
        raise HTTPException(403, "Token is not authorized for GreenU")
    return data


def upstream_client():
    # No automatic retries for authentication or point-bearing deposits.
    with httpx.Client(timeout=settings().greenu_timeout_seconds, follow_redirects=False) as client:
        yield client


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accessCode: str = Field(pattern=r"^[a-fA-F0-9]{32}$")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/qr", dependencies=[Depends(device)])
def login(body: Login, response: Response, client: Annotated[httpx.Client, Depends(upstream_client)]):
    config = settings()
    try:
        result = client.post(config.token_url, data={
            "grant_type": GRANT, "client_id": "rvm-auth-backend",
            "client_secret": config.keycloak_client_secret.get_secret_value(),
            "access_code": body.accessCode,
        })
        payload = result.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Authentication service unavailable") from None
    if not isinstance(payload, dict):
        raise HTTPException(502, "Invalid authentication service response")
    if result.status_code != 200:
        if payload.get("error") == "invalid_grant":
            raise HTTPException(401, "Membership cannot be validated")
        raise HTTPException(503, "Authentication service unavailable")
    if not all(key in payload for key in ("access_token", "expires_in", "token_type", "member")):
        raise HTTPException(502, "Invalid authentication service response")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {"accessToken": payload["access_token"], "expiresIn": payload["expires_in"],
            "tokenType": payload["token_type"], "member": payload["member"]}


@app.get("/auth/me", dependencies=[Depends(device)])
def me(user: Annotated[dict, Depends(claims)]):
    return {"userId": user["sub"], "tenant": user["tenant"],
            "provider": user["identity_provider"], "memberId": user["external_member_id"]}


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recyclableType: str = Field(min_length=1, max_length=100)
    quantity: StrictInt = Field(gt=0, le=10000)


class Deposit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    depositedItems: list[Item] = Field(min_length=1, max_length=100)


def ledger():
    db = sqlite3.connect(settings().deposit_db, timeout=5)
    db.execute("CREATE TABLE IF NOT EXISTS deposits (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL, result TEXT)")
    return db


@app.post("/transactions", dependencies=[Depends(device)])
def deposit(body: Deposit, user: Annotated[dict, Depends(claims)],
            client: Annotated[httpx.Client, Depends(upstream_client)],
            idempotency_key: Annotated[str, Header(min_length=8, max_length=128)]):
    config = settings()
    payload = {"merchant": config.greenu_merchant, "binID": config.rvm_bin_id,
               "depositType": "quantity", "depositedItems": [item.model_dump() for item in body.depositedItems]}
    fingerprint = hashlib.sha256(json.dumps([user["sub"], payload], sort_keys=True).encode()).hexdigest()
    db = ledger()
    try:
        try:
            with db:
                db.execute("INSERT INTO deposits VALUES (?, ?, 'pending', NULL)", (idempotency_key, fingerprint))
        except sqlite3.IntegrityError:
            row = db.execute("SELECT fingerprint, state, result FROM deposits WHERE key=?", (idempotency_key,)).fetchone()
            if row[0] != fingerprint:
                raise HTTPException(409, "Idempotency key belongs to a different transaction")
            if row[1] == "success":
                return json.loads(row[2])
            raise HTTPException(409, "Transaction already attempted; verify upstream status before retrying")
        base = config.greenu_base_url.rstrip("/")
        if not base.startswith("https://") and base != "http://greenu-mock:8000":
            raise HTTPException(503, "GreenU URL must use HTTPS")
        try:
            result = client.post(base + "/recycle/member/" + user["external_member_id"] + "/deposit",
                                 headers={"api-key": config.greenu_api_key.get_secret_value()}, json=payload)
            data = result.json()
            if result.status_code == 200:
                if (not isinstance(data, dict) or type(data.get("pointsEarned")) is not int or type(data.get("memberBalanceUpdated")) is not int):
                    raise ValueError("Invalid deposit response")
                with db:
                    db.execute("UPDATE deposits SET state='success', result=? WHERE key=?", (json.dumps(data), idempotency_key))
                return data
            with db:
                db.execute("UPDATE deposits SET state='rejected' WHERE key=?", (idempotency_key,))
            raise HTTPException(502, "GreenU rejected deposit; transaction requires review")
        except (httpx.HTTPError, ValueError):
            with db:
                db.execute("UPDATE deposits SET state='unknown' WHERE key=?", (idempotency_key,))
            raise HTTPException(502, "Deposit outcome unknown; do not resubmit with a new key") from None
    finally:
        db.close()
