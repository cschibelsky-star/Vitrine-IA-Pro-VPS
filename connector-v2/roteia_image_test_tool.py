"""Isolated Roteia image test tool. Register with the existing FastMCP instance.

Requires ROTEIA_API_KEY in the connector runtime (server-side injection only).
No credential values are returned. No Core routing or production changes.
"""
import os
import time
import httpx

ALLOWED_MODELS = tuple(x.strip() for x in os.getenv("ROTEIA_TEST_MODELS", "").split(",") if x.strip())
BASE_URL = os.getenv("ROTEIA_API_BASE_URL", "").rstrip("/")

def register_roteia_image_test(mcp):
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def roteia_image_test(model: str, prompt: str, size: str = "1024x1024") -> dict:
        """Generate one image using an allowlisted Roteia model, returning safe metrics."""
        if not BASE_URL or not BASE_URL.startswith("https://"):
            return {"ok": False, "error": "roteia_base_url_not_configured"}
        if not ALLOWED_MODELS or model not in ALLOWED_MODELS:
            return {"ok": False, "error": "model_not_allowlisted"}
        if size not in ("1024x1024", "1536x1024", "1024x1536"):
            return {"ok": False, "error": "invalid_size"}
        if not prompt or len(prompt) > 2000:
            return {"ok": False, "error": "invalid_prompt"}
        key = os.getenv("ROTEIA_API_KEY")
        if not key:
            return {"ok": False, "error": "credential_not_configured"}
        started = time.monotonic()
        try:
            with httpx.Client(timeout=120, follow_redirects=False) as client:
                response = client.post(
                    BASE_URL + "/images/generations",
                    headers={"Authorization": "Bearer " + key},
                    json={"model": model, "prompt": prompt, "size": size, "n": 1},
                )
            elapsed = round(time.monotonic() - started, 3)
            if response.status_code != 200:
                return {"ok": False, "status_code": response.status_code, "elapsed_seconds": elapsed}
            payload = response.json()
            item = (payload.get("data") or [{}])[0]
            return {"ok": True, "model": model, "elapsed_seconds": elapsed,
                    "image_url": item.get("url"), "has_base64_image": bool(item.get("b64_json")),
                    "usage": payload.get("usage"), "revised_prompt": item.get("revised_prompt")}
        except (httpx.HTTPError, ValueError, IndexError, TypeError):
            return {"ok": False, "error": "request_failed", "elapsed_seconds": round(time.monotonic()-started, 3)}
