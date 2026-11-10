"""Local fixture only. Never use this service as a real membership authority."""
import os
import secrets
from fastapi import Depends, FastAPI, Header, HTTPException

app = FastAPI()
balance = 386


def authorized(api_key: str = Header()):
    if not secrets.compare_digest(api_key, os.environ["GREENU_API_KEY"]):
        raise HTTPException(401, "Unauthorized access to the API")


@app.post("/recycle/member/{access_code}", dependencies=[Depends(authorized)])
def member(access_code: str, body: dict):
    if access_code != os.environ["GREENU_ACCESS_CODE"]:
        raise HTTPException(404, "The membership cannot be validated")
    if body != {"merchant": "GreenAI"}:
        raise HTTPException(400, "Bad request")
    return {"membership": True, "memberID": "12AB34CD56EF78GH", "memberBalance": balance,
            "memberMaskedInfo": "C*** T** M**"}


@app.post("/recycle/member/{member_id}/deposit", dependencies=[Depends(authorized)])
def deposit(member_id: str, body: dict):
    global balance
    if member_id != "12AB34CD56EF78GH":
        raise HTTPException(404, "The membership cannot be validated")
    if body.get("merchant") != "GreenAI" or body.get("depositType") != "quantity":
        raise HTTPException(400, "Bad request")
    points = sum(item["quantity"] for item in body["depositedItems"])
    balance += points
    return {"message": "Member balance is updated", "pointsEarned": points, "memberBalanceUpdated": balance}
