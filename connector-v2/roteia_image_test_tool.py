"""Isolated image test via the Centro IA broker; Roteia credentials remain in Core.

Only an authorized internal broker token is used by this connector. The Core owns
provider selection, capability discovery, cost telemetry and the Roteia API key.
"""
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlparse
import httpx


def register_roteia_image_test(mcp):
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def roteia_image_test(prompt: str, quality_profile: str = "balanced") -> dict:
        """Request one image from Centro IA using its existing authenticated broker."""
        if not isinstance(prompt, str) or not 5 <= len(prompt.strip()) <= 2000:
            return {"ok": False, "error": "invalid_prompt"}
        if quality_profile not in ("balanced", "quality", "economy", "fast"):
            return {"ok": False, "error": "invalid_quality_profile"}
        url = os.getenv("CENTRO_IA_BROKER_URL", "").strip()
        token = os.getenv("CENTRO_IA_INTERNAL_TOKEN", "").strip()
        project = os.getenv("CENTRO_IA_PROJECT_ID", "vitrine-ia-pro-vps").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query or not url.endswith("/api/internal/centro-ia/execute"):
            return {"ok": False, "error": "broker_url_not_configured"}
        if not project:
            return {"ok": False, "error": "broker_identity_not_configured"}
        body = json.dumps(
            {"project_id": project, "capability": "image_generation",
             "input": {"user": prompt.strip(), "quality_profile": quality_profile}},
            separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        headers = {"X-Vitrine-Project": project, "Content-Type": "application/json"}
        signing_key = os.getenv("CENTRO_IA_SERVICE_PRIVATE_KEY_B64", "").strip()
        if signing_key:
            try:
                from nacl.signing import SigningKey
                key_bytes = base64.b64decode(signing_key, validate=True)
                if len(key_bytes) != 32:
                    return {"ok": False, "error": "invalid_service_identity"}
                timestamp = str(int(time.time()))
                nonce = secrets.token_hex(16)
                canonical = "\n".join(
                    ("POST", urlparse(url).path, project, timestamp, nonce,
                     hashlib.sha256(body).hexdigest())
                ).encode("utf-8")
                signature = SigningKey(key_bytes).sign(canonical).signature
                headers.update({
                    "X-Vitrine-Timestamp": timestamp, "X-Vitrine-Nonce": nonce,
                    "X-Vitrine-Signature": base64.b64encode(signature).decode("ascii"),
                    "X-Vitrine-Signature-Alg": "Ed25519",
                })
            except (ImportError, ValueError, TypeError):
                return {"ok": False, "error": "invalid_service_identity"}
        elif token:
            headers["Authorization"] = "Bearer " + token
        else:
            return {"ok": False, "error": "broker_identity_not_configured"}
        started = time.monotonic()
        try:
            with httpx.Client(timeout=135, follow_redirects=False, trust_env=False) as client:
                response = client.post(
                    url,
                    headers=headers,
                    content=body,
                )
            elapsed = round(time.monotonic() - started, 3)
            if response.status_code != 200:
                return {"ok": False, "error": "broker_request_rejected",
                        "status_code": response.status_code, "elapsed_seconds": elapsed}
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                return {"ok": False, "error": "broker_generation_failed", "elapsed_seconds": elapsed}
            asset_url = payload.get("asset_url")
            has_image = bool(payload.get("asset_base64"))
            if not asset_url and not has_image:
                return {"ok": False, "error": "no_image_returned", "elapsed_seconds": elapsed}
            return {"ok": True, "model": payload.get("model"),
                    "image_url": asset_url, "has_base64_image": has_image,
                    "elapsed_seconds": elapsed}
        except (httpx.HTTPError, ValueError, TypeError):
            return {"ok": False, "error": "broker_request_failed",
                    "elapsed_seconds": round(time.monotonic() - started, 3)}
