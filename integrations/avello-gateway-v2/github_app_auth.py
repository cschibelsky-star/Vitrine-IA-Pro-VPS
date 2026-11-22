"""Isolated GitHub App installation-token provider; no network call on import.

This module is NOT wired to MCP or dispatch. Private key must be injected only
at runtime by a trusted server-side secret manager. Never log JWTs or tokens.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
TARGET_REPO = "JARVIS"
MAX_RESPONSE = 8192


class AppAuthError(Exception):
    """Sanitized authentication failure."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_app_jwt(app_id: str, private_key_pem: bytes, now: int | None = None) -> str:
    """Sign a short-lived RS256 GitHub App JWT; never accept arbitrary algorithms."""
    if not re.fullmatch(r"[1-9][0-9]{0,15}", app_id):
        raise AppAuthError("invalid_app_id")
    if not private_key_pem or len(private_key_pem) > 32768:
        raise AppAuthError("invalid_private_key")
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        key = serialization.load_pem_private_key(private_key_pem, password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("not RSA")
        issued = int(time.time()) if now is None else int(now)
        header = _b64url(b'{"alg":"RS256","typ":"JWT"}')
        payload = _b64url(json.dumps(
            {"iat": issued - 60, "exp": issued + 540, "iss": app_id},
            separators=(",", ":")).encode("utf-8"))
        signing_input = (header + "." + payload).encode("ascii")
        signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return signing_input.decode("ascii") + "." + _b64url(signature)
    except (ValueError, TypeError, ImportError) as exc:
        raise AppAuthError("jwt_signing_unavailable") from None


def installation_token(app_id: str, installation_id: str, private_key_pem: bytes,
                       opener=None, now: int | None = None) -> str:
    """Request a repository- and permission-restricted installation token.

    This does not prove the installation belongs to the app until GitHub
    successfully authenticates the signed JWT. Never persist returned tokens.
    """
    if not re.fullmatch(r"[1-9][0-9]{0,15}", installation_id):
        raise AppAuthError("invalid_installation_id")
    jwt = make_app_jwt(app_id, private_key_pem, now=now)
    url = f"{API}/app/installations/{installation_id}/access_tokens"
    body = json.dumps({"repositories": [TARGET_REPO],
                       "permissions": {"actions": "write", "contents": "read"}},
                      separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + jwt,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "vitrine-avello-isolated-app-auth",
    })
    try:
        client = opener if opener is not None else urllib.request.build_opener(NoRedirect())
        with client.open(req, timeout=15) as response:
            if response.status != 201:
                raise AppAuthError("unexpected_token_status")
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise AppAuthError("token_response_too_large")
        data = json.loads(raw)
        token = data.get("token")
        perms = data.get("permissions", {})
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,512}", token):
            raise AppAuthError("invalid_token_response")
        if perms.get("actions") != "write":
            raise AppAuthError("actions_write_not_granted")
        return token
    except urllib.error.HTTPError as exc:
        raise AppAuthError(f"github_http_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise AppAuthError("github_unreachable") from None
    except (ValueError, TypeError, AttributeError):
        raise AppAuthError("invalid_token_response") from None


def token_from_server_environment(opener=None) -> str:
    """Explicit opt-in only. Not used by the existing dispatch adapter."""
    app_id = os.environ.get("VIA_GITHUB_APP_ID", "")
    installation_id = os.environ.get("VIA_GITHUB_APP_INSTALLATION_ID", "")
    pem = os.environ.get("VIA_GITHUB_APP_PRIVATE_KEY_PEM", "")
    if not pem:
        raise AppAuthError("private_key_not_configured")
    return installation_token(app_id, installation_id, pem.replace("\\n", "\n").encode(),
                              opener=opener)
