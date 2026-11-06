"""Authenticated MCP bridge for Avello GPT and Claude (HML only)."""
import hmac
import os
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from bridge import ask, GPT_MODELS, GPT_DEFAULT_MODEL, list_models, smoke_probe
from oauth_provider import GoogleProvider, install_oauth, SCOPE

oauth_provider = GoogleProvider() if os.getenv("AVELLO_OAUTH_ENABLED", "false").lower() == "true" else None

mcp = FastMCP("Vitrine Avello Private", host="0.0.0.0",
              port=int(os.getenv("PORT", "8765")),
              stateless_http=True, json_response=True,
              auth_server_provider=oauth_provider,
              auth=oauth_provider.settings if oauth_provider else None)

@mcp.tool()
def avello_status() -> dict:
    """Safe readiness details without disclosing secrets."""
    return {
        "gpt_key_present": bool(os.getenv("AVELLO_GPT_API_KEY")),
        "claude_key_present": bool(os.getenv("AVELLO_CLAUDE_API_KEY")),
        "claude_model_configured": bool(os.getenv("AVELLO_CLAUDE_MODEL")),
        "calls_enabled": os.getenv("AVELLO_CALLS_ENABLED", "false").lower() == "true",
        "gpt_models": list(GPT_MODELS),
        "gpt_default_model": GPT_DEFAULT_MODEL,
        "claude_default_model": os.getenv("AVELLO_CLAUDE_MODEL", ""),
        "remote_execution": False,
        "google_oauth_enabled": oauth_provider is not None,
    }

@mcp.tool(meta={"securitySchemes": [{"type": "oauth2", "scopes": [SCOPE]}]})
def avello_ask(prompt: str, provider: str = "gpt", model: str = "") -> dict:
    """Ask Avello for development help. Use provider=claude for implementation
    (configured Opus), provider=gpt for review (default Sol). Send only necessary
    code/context, never credentials. Returns suggestions/code; the coordinating
    assistant must review, apply and test changes with its own project tools.
    Never executes returned code or edits projects.
    """
    return ask(prompt, provider, model or None)

@mcp.tool()
def avello_models(provider: str = "gpt") -> dict:
    """Read the provider model catalog without inference; cached per process."""
    return list_models(provider)

@mcp.tool()
def avello_smoke(provider: str = "gpt") -> dict:
    """Run or retrieve an authorized one-shot connectivity probe; no automatic retries."""
    return smoke_probe(provider)

class BearerGuard(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        token = os.getenv("MCP_BEARER_TOKEN", "")
        if len(token) < 32:
            return PlainTextResponse("Server unavailable", status_code=503)
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied, "Bearer " + token):
            return PlainTextResponse("Unauthorized", status_code=401)
        return await call_next(request)

app = mcp.streamable_http_app()
if oauth_provider:
    install_oauth(app, oauth_provider)
else:
    app.add_middleware(BearerGuard)

