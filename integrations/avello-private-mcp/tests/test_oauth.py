"""Offline OAuth contract/security tests. No calls to Google or Avello."""
import asyncio
import base64
import hashlib
import json
import time
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from mcp.server.fastmcp import FastMCP
from starlette.responses import RedirectResponse
from starlette.testclient import TestClient
from oauth_provider import GoogleProvider, Store, ORIGIN, RESOURCE, GOOGLE_ISSUER, SCOPE, install_oauth

REDIRECT = "https://chatgpt.com/connector/oauth/test-callback-id"
VERIFIER = "v"*64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
IDENTITY = {"iss":GOOGLE_ISSUER,"sub":"test-owner-subject","email":"owner@example.test","email_verified":True}


@pytest.fixture
def oauth_env(monkeypatch, tmp_path):
    for key, value in {"AVELLO_GOOGLE_CLIENT_ID":"test-google-client", "AVELLO_GOOGLE_CLIENT_SECRET":"test-secret",
        "AVELLO_OAUTH_SESSION_SECRET":"session-test-"+"s"*48, "AVELLO_OAUTH_ALLOWED_EMAIL":"owner@example.test",
        "MCP_BEARER_TOKEN":"d"*48}.items():
        monkeypatch.setenv(key,value)
    provider = GoogleProvider(tmp_path/"oauth.sqlite3")
    provider.google.authorize_redirect = AsyncMock(return_value=RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth"))
    provider.google.authorize_access_token = AsyncMock(return_value={"userinfo":IDENTITY})
    mcp = FastMCP("OAuth test", host="0.0.0.0", stateless_http=True, json_response=True,
                  auth_server_provider=provider, auth=provider.settings)
    @mcp.tool()
    def readiness() -> dict:
        return {"ready":True}
    app = mcp.streamable_http_app()
    install_oauth(app,provider)
    with TestClient(app,base_url=ORIGIN,follow_redirects=False) as client:
        yield provider,client


def register(client, **overrides):
    return client.post("/register",json={"client_name":"ChatGPT test", "redirect_uris":[REDIRECT],
        "token_endpoint_auth_method":"none", "grant_types":["authorization_code","refresh_token"],
        "response_types":["code"], "scope":SCOPE, **overrides})


def begin(client, client_id, **overrides):
    return client.get("/authorize",params={"client_id":client_id,"response_type":"code","redirect_uri":REDIRECT,
        "code_challenge":CHALLENGE,"code_challenge_method":"S256","scope":SCOPE,"state":"client-state",
        "resource":RESOURCE, **overrides})


def sign_in(client, client_id):
    response=begin(client,client_id)
    assert response.status_code==302,response.text
    start=client.get(response.headers["location"])
    assert start.status_code in (302,307)
    callback=client.get("/oauth/google/callback?state=mock-state&code=mock-google-code")
    assert callback.status_code==303,callback.text
    page=client.get(callback.headers["location"])
    assert page.status_code==200
    import re
    return re.search(r'name="csrf" value="([A-Za-z0-9_-]+)"',page.text).group(1)


def grant(client, csrf):
    response=client.post("/oauth/consent",data={"csrf":csrf,"decision":"allow"},headers={"Origin":ORIGIN})
    assert response.status_code==303,response.text
    params=parse_qs(urlparse(response.headers["location"]).query)
    assert params["state"]==["client-state"]
    return params["code"][0]


def token_form(client_id, code):
    return {"client_id":client_id,"grant_type":"authorization_code","code":code,
            "code_verifier":VERIFIER,"redirect_uri":REDIRECT,"resource":RESOURCE}


def test_http_pkce_tokens_refresh_revocation_and_private_diagnostics(oauth_env):
    provider,client=oauth_env
    unauth=client.get("/mcp")
    assert unauth.status_code==401
    assert "oauth-protected-resource/mcp" in unauth.headers["www-authenticate"]
    metadata=client.get("/.well-known/oauth-authorization-server").json()
    assert metadata["code_challenge_methods_supported"]==["S256"]
    assert metadata["token_endpoint_auth_methods_supported"]==["none"]
    assert client.get("/.well-known/oauth-protected-resource/mcp").json()["resource"]==RESOURCE
    reg=register(client)
    assert reg.status_code==201,reg.text
    cid=reg.json()["client_id"]
    code=grant(client,sign_in(client,cid))
    form=token_form(cid,code)
    assert client.post("/token",data={**form,"code_verifier":"wrong"}).status_code==400
    assert client.post("/token",data={**form,"resource":"https://other.example"}).status_code==400
    second=register(client).json()["client_id"]
    assert client.post("/token",data={**form,"client_id":second}).status_code==400
    response=client.post("/token",data=form)
    assert response.status_code==200,response.text
    tokens=response.json()
    assert client.post("/token",data=form).status_code==400
    def discover(access):
        return client.post("/mcp",headers={"Authorization":"Bearer "+access,"Accept":"application/json, text/event-stream"},
            json={"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
    assert discover(tokens["access_token"]).status_code==200
    assert discover("d"*48).status_code==200
    refresh={"client_id":cid,"grant_type":"refresh_token","refresh_token":tokens["refresh_token"],"resource":RESOURCE}
    rotated=client.post("/token",data=refresh)
    assert rotated.status_code==200,rotated.text
    assert client.post("/token",data=refresh).status_code==400
    assert discover(tokens["access_token"]).status_code==401
    assert discover(rotated.json()["access_token"]).status_code==200
    assert client.post("/revoke",data={"client_id":cid,"token":rotated.json()["refresh_token"]}).status_code==200
    assert discover(rotated.json()["access_token"]).status_code==401
    # No issued credentials, Google identity or authorization codes stored in plaintext.
    raw=open(provider.store.path,"rb").read()
    for value in (tokens["access_token"],tokens["refresh_token"],code,"owner@example.test"):
        assert value.encode() not in raw


@pytest.mark.parametrize("uri",["http://chatgpt.com/connector/oauth/a","https://chatgpt.com.evil.test/connector/oauth/a",
    "https://evil.test/callback","https://chatgpt.com/connector/oauth/a?evil=1","https://chatgpt.com/connector/oauth/a#fragment"])
def test_untrusted_redirects_denied(oauth_env,uri):
    _,client=oauth_env
    assert register(client,redirect_uris=[uri]).status_code==400


def test_unbound_callbacks_wrong_owner_and_failed_oidc_are_denied(oauth_env):
    provider,client=oauth_env
    assert client.get("/oauth/google/callback?code=unbound").status_code==400
    cid=register(client).json()["client_id"]
    for user in ({**IDENTITY,"email":"someone@example.test"},{**IDENTITY,"email_verified":False},
                 {**IDENTITY,"iss":"https://evil.test"},{**IDENTITY,"sub":""}):
        response=begin(client,cid)
        client.get(response.headers["location"])
        provider.google.authorize_access_token.return_value={"userinfo":user}
        assert client.get("/oauth/google/callback?code=mock").status_code==403
        assert client.get("/oauth/consent").status_code==400
    response=begin(client,cid)
    client.get(response.headers["location"])
    provider.google.authorize_access_token.side_effect=ValueError("invalid nonce or signature")
    assert client.get("/oauth/google/callback?code=mock").status_code==403


def test_consent_csrf_cancel_and_no_code_before_consent(oauth_env):
    provider,client=oauth_env
    cid=register(client).json()["client_id"]
    csrf=sign_in(client,cid)
    with provider.store.connect() as db:
        assert db.execute("SELECT count(*) FROM oauth_records WHERE kind='code'").fetchone()[0]==0
    for origin,nonce in (("https://evil.test",csrf),(ORIGIN,"wrong")):
        assert client.post("/oauth/consent",data={"csrf":nonce,"decision":"allow"},headers={"Origin":origin}).status_code==403
    response=client.post("/oauth/consent",data={"csrf":csrf,"decision":"deny"},headers={"Origin":ORIGIN})
    assert response.status_code==303
    assert parse_qs(urlparse(response.headers["location"]).query)["error"]==["access_denied"]
    assert client.post("/oauth/consent",data={"csrf":csrf,"decision":"allow"},headers={"Origin":ORIGIN}).status_code==400


def test_expired_tokens_and_resource_scope_restrictions(oauth_env,monkeypatch):
    provider,client=oauth_env
    cid=register(client).json()["client_id"]
    assert register(client,scope="admin").status_code==400
    assert register(client,token_endpoint_auth_method="client_secret_post").status_code==400
    for params in ({"resource":"https://other.test"},{"code_challenge_method":"plain"},{"code_challenge":"bad"},{"scope":"admin"}):
        response=begin(client,cid,**params)
        assert response.status_code==400 or "error=" in response.headers.get("location", "")
    issued=provider.issue(cid,[SCOPE],"google:test")
    with provider.store.connect() as db:
        db.execute("UPDATE oauth_records SET expires=0 WHERE kind IN ('access','refresh')")
    assert asyncio.run(provider.load_access_token(issued.access_token)) is None
    # Revoking an account locally invalidates previously issued credentials too.
    issued=provider.issue(cid,[SCOPE],"google:test")
    provider.email="other@example.test"
    assert asyncio.run(provider.load_access_token(issued.access_token)) is None


def test_cookie_and_response_protections(oauth_env):
    _,client=oauth_env
    cid=register(client).json()["client_id"]
    response=begin(client,cid)
    start=client.get(response.headers["location"])
    cookie=start.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert start.headers["referrer-policy"]=="no-referrer"
    assert "frame-ancestors 'none'" in start.headers["content-security-policy"]
    assert client.post("/token",content=b"x"*140000).status_code==413


def test_real_oidc_library_verifies_signature_nonce_issuer_audience_expiry(oauth_env):
    provider,_=oauth_env
    google=provider.google
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid":"test-key","use":"sig","alg":"RS256"})
    google.load_server_metadata=AsyncMock(return_value={"issuer":GOOGLE_ISSUER,"id_token_signing_alg_values_supported":["RS256"]})
    google.fetch_jwk_set=AsyncMock(return_value={"keys":[jwk]})
    claims={**IDENTITY,"aud":"test-google-client","iat":int(time.time()),"exp":int(time.time())+300,"nonce":"expected-nonce"}
    def parse(data, sign_key=key):
        encoded=jwt.encode(data,sign_key,algorithm="RS256",headers={"kid":"test-key"})
        return asyncio.run(google.parse_id_token({"id_token":encoded,"access_token":"mock-access"},nonce="expected-nonce",leeway=0))
    assert parse(claims)["sub"]==IDENTITY["sub"]
    for bad in ({"nonce":"wrong"},{"aud":"other-client"},{"iss":"https://evil.test"},{"exp":int(time.time())-10}):
        with pytest.raises(Exception):
            parse({**claims,**bad})
    with pytest.raises(Exception):
        parse(claims,rsa.generate_private_key(public_exponent=65537,key_size=2048))


def test_store_single_use_and_persistence(tmp_path):
    path=tmp_path/"store.sqlite3"
    store=Store(path,"s"*48)
    store.put("code","random-code",{"owner":"test"},120)
    restarted=Store(path,"s"*48)
    assert restarted.get("code","random-code",consume=True)=={"owner":"test"}
    assert store.get("code","random-code",consume=True) is None
    store.put("flow","expired",{},-1)
    assert store.get("flow","expired") is None
