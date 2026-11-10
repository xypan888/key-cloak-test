"""Read local .env, authenticate once, and call /auth/me. Never submits a deposit."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

root = Path(__file__).resolve().parents[1]
for line in (root / ".env").read_text().splitlines():
    if line.strip() and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
base = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
headers = {"X-RVM-API-Key": os.environ["RVM_API_KEY"], "Content-Type": "application/json"}
try:
    request = Request(base + "/auth/qr", headers=headers,
                      data=json.dumps({"accessCode": os.environ["GREENU_ACCESS_CODE"]}).encode())
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    print(json.dumps({"expiresIn": result["expiresIn"], "member": result["member"]}, ensure_ascii=False))
    headers["Authorization"] = "Bearer " + result["accessToken"]
    with urlopen(Request(base + "/auth/me", headers=headers), timeout=15) as response:
        print(json.dumps(json.load(response), ensure_ascii=False))
except HTTPError as error:
    print(f"Request failed: HTTP {error.code}")
    raise SystemExit(1)
