"""Full local integration check. Refuses non-mock config; uses fake points only."""
import json
import os
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

root=Path(__file__).resolve().parents[1]
for line in (root/'.env').read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#'):
        key,value=line.split('=',1)
        os.environ.setdefault(key.strip(),value.strip().strip('\"\''))
if os.environ['GREENU_BASE_URL'] != 'http://greenu-mock:8000':
    raise SystemExit('Refusing to run: integration test requires the local GreenU mock')
base=os.environ.get('BACKEND_URL','http://localhost:8000').rstrip('/')
headers={'X-RVM-API-Key':os.environ['RVM_API_KEY'],'Content-Type':'application/json'}

def request(path, body=None, extra=None):
    req=Request(base+path,headers={**headers,**(extra or {})},
                data=None if body is None else json.dumps(body).encode())
    try:
        with urlopen(req,timeout=30) as response:
            return response.status,json.load(response)
    except HTTPError as error:
        return error.code,json.load(error)

status,login=request('/auth/qr',{'accessCode':os.environ['GREENU_ACCESS_CODE']})
assert status==200,(status,login)
assert login['expiresIn']==180
assert login['member']['maskedInfo']=='C*** T** M**'
auth={'Authorization':'Bearer '+login['accessToken']}
status,member=request('/auth/me',extra=auth)
assert status==200,(status,member)
assert member['tenant']=='hku' and member['memberId']=='12AB34CD56EF78GH'
status,login2=request('/auth/qr',{'accessCode':os.environ['GREENU_ACCESS_CODE']})
assert status==200
status,member2=request('/auth/me',extra={'Authorization':'Bearer '+login2['accessToken']})
assert status==200 and member2['userId']==member['userId']
assert request('/auth/qr',{'accessCode':'ABC'})[0]==422
assert request('/auth/qr',{'accessCode':'0'*32})[0]==401
assert request('/auth/qr',{'accessCode':os.environ['GREENU_ACCESS_CODE']}, {'X-RVM-API-Key':'wrong'})[0]==401
assert request('/auth/me',extra={'Authorization':'Bearer invalid'})[0]==401
# Syntactically valid JWT with a changed signature must fail verification.
parts=login['accessToken'].split('.')
parts[2]=('B' if parts[2][0]!='B' else 'C')+parts[2][1:]
assert request('/auth/me',extra={'Authorization':'Bearer '+'.'.join(parts)})[0]==401
body={'depositedItems':[{'recyclableType':'Plastic Bottles','quantity':2}]}
transaction={**auth,'Idempotency-Key':'mock-'+str(uuid.uuid4())}
status,result=request('/transactions',body,transaction)
assert status==200,(status,result)
assert result['pointsEarned']==2
status,repeated=request('/transactions',body,transaction)
assert status==200 and result==repeated
body['depositedItems'][0]['quantity']=3
assert request('/transactions',body,transaction)[0]==409
print('PASS: real Keycloak signed token, identity mapping, invalid QR/device/signature, mock deposit and idempotency')
