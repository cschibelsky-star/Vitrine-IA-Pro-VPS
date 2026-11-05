"""Private Avello MCP bridge. No shell, filesystem, Git or deploy operations."""
import hmac
import json
import os
import threading
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

PROVIDER_URL = "https://avellogateway.online/v1/responses"
MODELS = ("gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna")
MAX_CHARS = 12000
_CONCURRENCY = threading.BoundedSemaphore(2)
mcp = FastMCP("Vitrine Avello Private", host="127.0.0.1",
              port=int(os.getenv("PORT", "8765")),
              stateless_http=True, json_response=True)


def request_model(prompt: str, model: str = "gpt-5.6-terra") -> dict:
    if model not in MODELS:
        return {"status": "rejected", "reason": "model_not_allowed"}
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_CHARS:
        return {"status": "rejected", "reason": "invalid_prompt"}
    if os.getenv("AVELLO_PAID_ENABLED", "false").lower() != "true":
        return {"status": "blocked", "reason": "paid_calls_disabled"}
    # This flag is an additional deployment hold; not a financial budget control.
    api_key = os.getenv("AVELLO_API_KEY", "")
    if not api_key:
        return {"status": "not_configured"}
    if not _CONCURRENCY.acquire(blocking=False):
        return {"status": "busy"}
    try:
        body = json.dumps({"model": model, "input": prompt, "store": False}).encode("utf-8")
        req = urllib.request.Request(PROVIDER_URL, data=body,
                                     headers={"Authorization": "Bearer " + api_key,
                                              "Content-Type": "application/json"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=65) as response:
                payload = json.loads(response.read(2_000_000))
        except urllib.error.HTTPError as error:
            return {"status": "provider_error", "http_status": error.code}
        except (urllib.error.URLError, TimeoutError):
            return {"status": "network_error"}
        texts = []
        if not isinstance(payload, dict):
            return {"status": "invalid_provider_response"}
        for item in payload.get("output", []):
            if isinstance(item, dict):
                for part in item.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        texts.append(str(part.get("text", "")))
        return {"status": "ok", "model_requested": model,
                "provider_model": payload.get("model"),
                "text": "\n".join(texts)[:60000], "usage": payload.get("usage", {})}
    finally:
        _CONCURRENCY.release()


@mcp.tool()
def avello_status() -> dict:
    """Return safe local configuration status; does not make an API request."""
    return {"key_configured": bool(os.getenv("AVELLO_API_KEY")),
            "paid_enabled": os.getenv("AVELLO_PAID_ENABLED", "false").lower() == "true",
            "models": list(MODELS), "execution_capability": False}


@mcp.tool()
def avello_ask(prompt: str, model: str = "gpt-5.6-terra") -> dict:
    """Make a paid API call only if deployment enables it; never execute model output."""
    return request_model(prompt, model)


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
