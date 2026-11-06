"""Private MCP OAuth broker: SDK PKCE + verified Google OIDC, owner only."""
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import time
from collections import deque
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from cryptography.fernet import Fernet
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError,
    RefreshToken, RegistrationError, TokenError, construct_redirect_uri,
)
from mcp.server.auth.routes import build_metadata
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import RequestBodyLimitMiddleware
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

ORIGIN = "https://avello.hml.vitrineiapro.com.br"
RESOURCE = ORIGIN + "/mcp"
CALLBACK = ORIGIN + "/oauth/google/callback"
SCOPE = "avello:use"
GOOGLE_ISSUER = "https://accounts.google.com"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def allowed_redirect(uri):
    # Each exact URI is also bound to its registered client by the SDK.
    return bool(re.fullmatch(
        r"https://chatgpt\.com/(?:connector_platform_oauth_redirect|connector/oauth/[A-Za-z0-9_-]{1,160})",
        str(uri),
    ))


class Store:
    """Encrypted records and hashed token keys; single-use transitions are atomic."""
    def __init__(self, path, secret):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS oauth_records (kind TEXT, key TEXT, data BLOB, expires REAL, family TEXT, PRIMARY KEY(kind,key))")
        os.chmod(self.path, 0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def put(self, kind, key, value, ttl, family=""):
        with self.connect() as db:
            db.execute("DELETE FROM oauth_records WHERE expires<=?", (time.time(),))
            if db.execute("SELECT count(*) FROM oauth_records").fetchone()[0] >= 2000:
                raise RuntimeError("OAuth storage capacity reached")
            data = self.cipher.encrypt(json.dumps(value).encode())
            db.execute("INSERT OR REPLACE INTO oauth_records VALUES(?,?,?,?,?)",
                       (kind, digest(key), data, time.time()+ttl, family))

    def get(self, kind, key, consume=False):
        with self.connect() as db:
            if consume:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data,expires FROM oauth_records WHERE kind=? AND key=?",
                             (kind, digest(key))).fetchone()
            if consume:
                db.execute("DELETE FROM oauth_records WHERE kind=? AND key=?", (kind, digest(key)))
            if not row or row[1] <= time.time():
                return None
            return json.loads(self.cipher.decrypt(row[0]))

    def revoke(self, family):
        with self.connect() as db:
            db.execute("DELETE FROM oauth_records WHERE family=?", (family,))


class GoogleProvider:
    def __init__(self, path=None):
        self.secret = os.getenv("AVELLO_OAUTH_SESSION_SECRET", "")
        self.email = os.getenv("AVELLO_OAUTH_ALLOWED_EMAIL", "").strip().lower()
        if len(self.secret) < 32 or not self.email or not os.getenv("AVELLO_GOOGLE_CLIENT_ID") or not os.getenv("AVELLO_GOOGLE_CLIENT_SECRET"):
            raise RuntimeError("Google OAuth configuration incomplete")
        self.store = Store(path or "/data/avello-oauth.sqlite3", self.secret)
        self.registration = ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE])
        self.revocation = RevocationOptions(enabled=True)
        self.settings = AuthSettings(issuer_url=ORIGIN, resource_server_url=RESOURCE,
            validate_token_resource=True, required_scopes=[SCOPE],
            client_registration_options=self.registration, revocation_options=self.revocation)
        oauth = OAuth()
        self.google = oauth.register("google", client_id=os.environ["AVELLO_GOOGLE_CLIENT_ID"],
            client_secret=os.environ["AVELLO_GOOGLE_CLIENT_SECRET"],
            server_metadata_url=GOOGLE_ISSUER+"/.well-known/openid-configuration",
            client_kwargs={"scope":"openid email", "code_challenge_method":"S256", "timeout":15})

    async def get_client(self, client_id):
        data = self.store.get("client", client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info):
        if not client_info.redirect_uris or not all(allowed_redirect(x) for x in client_info.redirect_uris):
            raise RegistrationError("invalid_redirect_uri", "Only ChatGPT callbacks are accepted")
        if client_info.token_endpoint_auth_method != "none":
            raise RegistrationError("invalid_client_metadata", "Use the public PKCE client method: none")
        if set((client_info.scope or "").split()) != {SCOPE}:
            raise RegistrationError("invalid_client_metadata", "Invalid scope")
        self.store.put("client", client_info.client_id, client_info.model_dump(mode="json"), 90*86400)

    async def authorize(self, client, params):
        if params.resource != RESOURCE or set(params.scopes or []) != {SCOPE}:
            raise AuthorizeError("invalid_request", "Expected the Avello resource and scope")
        if not allowed_redirect(params.redirect_uri) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge):
            raise AuthorizeError("invalid_request", "Invalid callback or PKCE challenge")
        flow = secrets.token_urlsafe(32)
        self.store.put("flow", flow, {"client_id":client.client_id,"params":params.model_dump(mode="json")}, 600)
        return ORIGIN+"/oauth/google/start?flow="+flow

    async def load_authorization_code(self, client, authorization_code):
        data = self.store.get("code", authorization_code)
        if not data or data["client_id"] != client.client_id or data["email"] != self.email:
            return None
        return AuthorizationCode(code=authorization_code, **{k:v for k,v in data.items() if k!="email"})

    def issue(self, client_id, scopes, subject, family=None):
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        family = family or secrets.token_hex(16)
        common = {"client_id":client_id,"scopes":scopes,"subject":subject,"resource":RESOURCE,
                  "email":self.email,"family":family}
        self.store.put("access", access, {**common,"expires_at":int(time.time())+3600}, 3600, family)
        self.store.put("refresh", refresh, {**common,"expires_at":int(time.time())+7*86400}, 7*86400, family)
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=3600,
                          refresh_token=refresh, scope=" ".join(scopes))

    async def exchange_authorization_code(self, client, authorization_code):
        data = self.store.get("code", authorization_code.code, consume=True)
        if not data or data["client_id"] != client.client_id or data["email"] != self.email:
            raise TokenError("invalid_grant", "Code expired or already used")
        return self.issue(client.client_id, authorization_code.scopes, authorization_code.subject)

    async def load_refresh_token(self, client, refresh_token):
        data = self.store.get("refresh", refresh_token)
        if not data or data["client_id"] != client.client_id or data["email"] != self.email:
            return None
        return RefreshToken(token=refresh_token, **{k:v for k,v in data.items() if k not in ("email","family")})

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        data = self.store.get("refresh", refresh_token.token, consume=True)
        if not data or data["client_id"] != client.client_id or data["email"] != self.email:
            raise TokenError("invalid_grant", "Refresh token expired or already used")
        if not set(scopes).issubset(data["scopes"]):
            raise TokenError("invalid_scope", "Scope escalation refused")
        self.store.revoke(data["family"])
        return self.issue(client.client_id, scopes, refresh_token.subject)

    async def load_access_token(self, token):
        # Existing private diagnostic token remains available for service health.
        legacy = os.getenv("MCP_BEARER_TOKEN", "")
        if len(legacy)>=32 and hmac.compare_digest(token, legacy):
            return AccessToken(token=token, client_id="private-diagnostics", scopes=[SCOPE], resource=RESOURCE)
        data = self.store.get("access", token)
        if not data or data["email"] != self.email:
            return None
        return AccessToken(token=token, **{k:v for k,v in data.items() if k not in ("email","family")})

    async def revoke_token(self, token):
        kind = "refresh" if isinstance(token, RefreshToken) else "access"
        data = self.store.get(kind, token.token)
        if data:
            self.store.revoke(data["family"])

    async def start(self, request):
        flow = request.query_params.get("flow", "")
        if not self.store.get("flow", flow):
            return PlainTextResponse("Solicitação expirada. Reconecte pelo ChatGPT.", status_code=400)
        request.session.clear()
        request.session["flow"] = flow
        try:
            return await self.google.authorize_redirect(request, CALLBACK,
                nonce=secrets.token_urlsafe(32), prompt="select_account", login_hint=self.email)
        except Exception:
            request.session.clear()
            return PlainTextResponse("Login Google temporariamente indisponível.", status_code=503)

    def checked_identity(self, user):
        return (user.get("iss") == GOOGLE_ISSUER and user.get("email_verified") is True
                and user.get("email", "").lower() == self.email and bool(user.get("sub")))

    async def callback(self, request):
        flow = request.session.get("flow", "")
        if not flow or not self.store.get("flow", flow):
            request.session.clear()
            return PlainTextResponse("Sessão inválida ou expirada.", status_code=400)
        try:
            token = await self.google.authorize_access_token(request,
                claims_options={"iss":{"essential":True,"value":GOOGLE_ISSUER},
                                "aud":{"essential":True,"value":os.environ["AVELLO_GOOGLE_CLIENT_ID"]}}, leeway=30)
            user = token.get("userinfo", {})
            if not self.checked_identity(user):
                raise ValueError("Owner account required")
        except Exception:
            request.session.clear()
            return PlainTextResponse("Acesso negado. Use a conta Google autorizada.", status_code=403)
        consent = secrets.token_urlsafe(32)
        self.store.put("consent", consent, {"flow":flow,"subject":"google:"+user["sub"]}, 300)
        request.session.clear()
        request.session["consent"] = consent
        return RedirectResponse(ORIGIN+"/oauth/consent", status_code=303)

    async def consent(self, request):
        csrf = request.session.get("consent", "")
        consent = self.store.get("consent", csrf)
        flow = self.store.get("flow", consent["flow"]) if consent else None
        if not flow:
            return PlainTextResponse("Autorização expirada. Reconecte pelo ChatGPT.", status_code=400)
        if request.method == "GET":
            client = await self.get_client(flow["client_id"])
            name = html.escape((client.client_name or "ChatGPT")[:100]) if client else "ChatGPT"
            target = html.escape(flow["params"]["redirect_uri"])
            return HTMLResponse(f'''<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Autorizar Vitrine Avello</title>
<body><main><h1>Conectar Vitrine Avello</h1><p>Conta: {html.escape(self.email)}</p>
<p>Autorizar {name} a consultar GPT e Claude para apoiar o desenvolvimento?</p>
<p>Os textos enviados ao conector serão processados pela Avello. Esta conexão permite gerar respostas e código.</p>
<p>Retorno: {target}</p><form method="post"><input type="hidden" name="csrf" value="{csrf}">
<button name="decision" value="allow">Autorizar conexão</button>
<button name="decision" value="deny">Cancelar</button></form></main></body></html>''')
        if request.headers.get("origin") != ORIGIN:
            return PlainTextResponse("Origem inválida.", status_code=403)
        form = await request.form()
        if not hmac.compare_digest(str(form.get("csrf", "")), csrf):
            return PlainTextResponse("Solicitação inválida.", status_code=403)
        consent = self.store.get("consent", csrf, consume=True)
        flow = self.store.get("flow", consent["flow"], consume=True) if consent else None
        request.session.clear()
        if not flow:
            return PlainTextResponse("Autorização já utilizada.", status_code=400)
        params = AuthorizationParams.model_validate(flow["params"])
        if form.get("decision") != "allow":
            return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), error="access_denied", state=params.state), status_code=303)
        code = secrets.token_urlsafe(32)
        data = AuthorizationCode(code=code, scopes=params.scopes or [SCOPE], expires_at=time.time()+120,
            client_id=flow["client_id"], code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=RESOURCE, subject=consent["subject"]).model_dump(mode="json", exclude={"code"})
        self.store.put("code", code, {**data,"email":self.email}, 120)
        return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state), status_code=303)


class OAuthHeaders(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.hits = deque(maxlen=120)

    async def dispatch(self, request, call_next):
        if request.url.path in ("/register", "/authorize", "/oauth/google/start"):
            now = time.monotonic()
            if len(self.hits)==120 and self.hits[0] > now-60:
                return PlainTextResponse("Too many requests", status_code=429)
            self.hits.append(now)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response


def install_oauth(app, provider):
    metadata = build_metadata(provider.settings.issuer_url, None, provider.registration, provider.revocation).model_dump(mode="json", exclude_none=True)
    metadata["token_endpoint_auth_methods_supported"] = ["none"]
    metadata["revocation_endpoint_auth_methods_supported"] = ["none"]
    handler = TokenHandler(provider, ClientAuthenticator(provider))

    async def discovery(request):
        return JSONResponse(metadata, headers={"Access-Control-Allow-Origin":"*"})

    async def exchange(request):
        # Validate the resource on both authorization-code and refresh exchanges.
        # Use the same Request for SDK processing so its cached form is reused.
        body = await request.body()
        if len(body)>16384:
            return JSONResponse({"error":"invalid_request"}, status_code=413)
        form = await request.form()
        if form.get("resource") != RESOURCE:
            return JSONResponse({"error":"invalid_target"}, status_code=400)
        return await handler.handle(request)

    async def revoke(request):
        # SDK 1.30's revocation form incorrectly requires a client_secret field
        # even for public clients. Keep RFC 7009 behavior for PKCE clients.
        if len(await request.body())>16384:
            return JSONResponse({"error":"invalid_request"}, status_code=413)
        form = await request.form()
        client = await provider.get_client(str(form.get("client_id", "")))
        value = str(form.get("token", ""))
        if not client or client.token_endpoint_auth_method!="none":
            return JSONResponse({"error":"invalid_client"}, status_code=401)
        if not value:
            return JSONResponse({"error":"invalid_request"}, status_code=400)
        token = await provider.load_refresh_token(client, value) or await provider.load_access_token(value)
        if token and token.client_id == client.client_id:
            await provider.revoke_token(token)
        return PlainTextResponse("", status_code=200)

    app.routes[:] = [r for r in app.routes if r.path not in ("/.well-known/oauth-authorization-server", "/token", "/revoke")]
    app.routes.extend([
        Route("/.well-known/oauth-authorization-server", discovery, methods=["GET"]),
        Route("/token", exchange, methods=["POST"]),
        Route("/revoke", revoke, methods=["POST"]),
        Route("/oauth/google/start", provider.start, methods=["GET"]),
        Route("/oauth/google/callback", provider.callback, methods=["GET"]),
        Route("/oauth/consent", provider.consent, methods=["GET","POST"]),
    ])
    app.add_middleware(SessionMiddleware, secret_key=provider.secret, session_cookie="__Host-avello-oauth",
                       max_age=600, same_site="lax", https_only=True)
    app.add_middleware(OAuthHeaders)
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=131072)
