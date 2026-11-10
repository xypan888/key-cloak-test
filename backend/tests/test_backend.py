import os
from unittest.mock import Mock
os.environ.update(KEYCLOAK_CLIENT_SECRET='client-test-secret', RVM_API_KEY='device-test-key',
                  RVM_BIN_ID='868618051694099', GREENU_BASE_URL='https://greenu.example', GREENU_API_KEY='upstream-test-key')
import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from app import main
from app.config import settings

HEADERS={'X-RVM-API-Key':'device-test-key'}
USER={'sub':'internal-user','tenant':'hku','identity_provider':'greenu','external_member_id':'12AB34CD56EF78GH'}

@pytest.fixture(autouse=True)
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('DEPOSIT_DB',str(tmp_path/'ledger.sqlite3'))
    settings.cache_clear()
    main.app.dependency_overrides.clear()
    yield
    main.app.dependency_overrides.clear()
    settings.cache_clear()

def transport(handler):
    client=httpx.Client(transport=httpx.MockTransport(handler))
    main.app.dependency_overrides[main.upstream_client]=lambda:client
    return TestClient(main.app)

def test_login_grant_and_response():
    def handler(request):
        from urllib.parse import parse_qs
        form=parse_qs(request.content.decode())
        assert form['grant_type']==[main.GRANT]
        assert form['access_code']==['A'*32]
        assert form['client_secret']==['client-test-secret']
        return httpx.Response(200,json={'access_token':'signed-token','expires_in':180,'token_type':'Bearer',
                                       'member':{'balance':386},'refresh_token':'not-returned'})
    response=transport(handler).post('/auth/qr',headers=HEADERS,json={'accessCode':'A'*32})
    assert response.status_code==200
    assert response.json()['accessToken']=='signed-token'
    assert 'refresh_token' not in response.json()
    assert response.headers['cache-control']=='no-store'

@pytest.mark.parametrize('code,status',[('ABC',422),('G'*32,422),('0'*32,401)])
def test_invalid_member(code,status):
    client=transport(lambda request:httpx.Response(400,json={'error':'invalid_grant'}))
    assert client.post('/auth/qr',headers=HEADERS,json={'accessCode':code}).status_code==status

def test_requires_device_and_explicit_code():
    client=TestClient(main.app)
    assert client.post('/auth/qr',headers={'X-RVM-API-Key':'wrong'},json={'accessCode':'A'*32}).status_code==401
    assert client.post('/auth/qr',headers=HEADERS,json={}).status_code==422

@pytest.mark.parametrize('status,error',[(401,'invalid_client'),(503,'temporarily_unavailable')])
def test_upstream_failure_is_not_member_failure(status,error):
    client=transport(lambda request:httpx.Response(status,json={'error':error}))
    response=client.post('/auth/qr',headers=HEADERS,json={'accessCode':'A'*32})
    assert response.status_code==503
    assert 'client-test-secret' not in response.text

def test_bad_token_rejected(monkeypatch):
    resolver=Mock()
    resolver.get_signing_key_from_jwt.side_effect=jwt.InvalidTokenError()
    monkeypatch.setattr(main,'jwks',lambda:resolver)
    assert TestClient(main.app).get('/auth/me',headers={**HEADERS,'Authorization':'Bearer wrong'}).status_code==401

def test_trusted_member_bin_and_idempotency():
    import json
    calls=[]
    def handler(request):
        calls.append(request)
        body=json.loads(request.content)
        assert request.url.path=='/recycle/member/12AB34CD56EF78GH/deposit'
        assert request.headers['api-key']=='upstream-test-key'
        assert body['binID']=='868618051694099'
        assert body['merchant']=='GreenAI'
        assert 'points' not in body
        return httpx.Response(200,json={'pointsEarned':3,'memberBalanceUpdated':389})
    client=transport(handler)
    main.app.dependency_overrides[main.claims]=lambda:USER
    body={'depositedItems':[{'recyclableType':'Plastic Bottles','quantity':2}]}
    headers={**HEADERS,'Idempotency-Key':'transaction-0001'}
    first=client.post('/transactions',headers=headers,json=body)
    second=client.post('/transactions',headers=headers,json=body)
    assert first.status_code==second.status_code==200
    assert first.json()==second.json()
    assert len(calls)==1
    body['depositedItems'][0]['quantity']=3
    assert client.post('/transactions',headers=headers,json=body).status_code==409

def test_deposit_timeout_no_retry():
    calls=[]
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('timeout',request=request)
    client=transport(handler)
    main.app.dependency_overrides[main.claims]=lambda:USER
    body={'depositedItems':[{'recyclableType':'Plastic Bottles','quantity':2}]}
    headers={**HEADERS,'Idempotency-Key':'transaction-0002'}
    assert client.post('/transactions',headers=headers,json=body).status_code==502
    assert client.post('/transactions',headers=headers,json=body).status_code==409
    assert len(calls)==1

def test_caller_cannot_choose_member():
    main.app.dependency_overrides[main.claims]=lambda:USER
    client=transport(lambda request:pytest.fail('Must reject before upstream call'))
    response=client.post('/transactions',headers={**HEADERS,'Idempotency-Key':'transaction-0003'},
                         json={'memberID':'other','depositedItems':[{'recyclableType':'Glass Bottles','quantity':1}]})
    assert response.status_code==422


@pytest.mark.parametrize('change,status', [({'exp':1},401),({'iss':'https://wrong'},401),
    ({'aud':'wrong-api'},401),({'tenant':'hkstp'},403),({'azp':'other-client'},403)])
def test_signed_token_claim_validation(monkeypatch,change,status):
    import time
    from cryptography.hazmat.primitives.asymmetric import rsa
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    resolver=Mock()
    resolver.get_signing_key_from_jwt.return_value=Mock(key=key.public_key())
    monkeypatch.setattr(main,'jwks',lambda:resolver)
    token=jwt.encode({**USER,'iat':int(time.time()),'exp':int(time.time())+180,
                      'iss':settings().keycloak_issuer,'aud':'replatform-api','azp':'rvm-auth-backend',**change},
                     key,algorithm='RS256')
    response=TestClient(main.app).get('/auth/me',headers={**HEADERS,'Authorization':'Bearer '+token})
    assert response.status_code==status


def test_malformed_login_response():
    client=transport(lambda request:httpx.Response(200,json=['unexpected']))
    assert client.post('/auth/qr',headers=HEADERS,json={'accessCode':'A'*32}).status_code==502
