"""Authenticated MCP bridge for Avello GPT and Claude (HML only)."""
import hmac
import os
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from bridge import ask, GPT_MODELS, GPT_DEFAULT_MODEL, list_models

mcp = FastMCP("Vitrine Avello Private", host="0.0.0.0",
              port=int(os.getenv("PORT", "8765")),
              stateless_http=True, json_response=True)

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
    }

@mcp.tool()
def avello_ask(prompt: str, provider: str = "gpt", model: str = "") -> dict:
    """Request inference only. Never executes returned code or edits projects."""
    return ask(prompt, provider, model or None)

@mcp.tool()
def avello_models(provider: str = "gpt") -> dict:
    """Read the provider model catalog without inference; cached per process."""
    return list_models(provider)

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
app.add_middleware(BearerGuard)
