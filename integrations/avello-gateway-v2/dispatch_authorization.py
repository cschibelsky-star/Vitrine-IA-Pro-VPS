"""Per-request authorization for a future GitHub Actions MCP dispatch tool.

Not connected to MCP ingress. Caller identity must come from verified auth,
never from a caller-controlled tool argument. Persistent nonce ledger is required.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import time
from pathlib import Path

from github_actions_dispatch import REPOSITORY, WORKFLOW, BRANCH

MAX_AGE_SECONDS = 120
IDENTITY_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:@-]{2,127}\Z")
NONCE_PATTERN = re.compile(r"[a-f0-9]{32,64}\Z")


class AuthorizationDenied(Exception):
    pass


def canonical_message(identity: str, nonce: str, issued_at: int) -> bytes:
    return f"v1\n{identity}\n{nonce}\n{issued_at}\n{REPOSITORY}\n{WORKFLOW}\n{BRANCH}".encode("utf-8")


def authorize(identity: str, nonce: str, issued_at: int, signature: str, *, now: int | None = None) -> dict:
    """Validate one signed authorization and atomically consume its nonce.

    The signing key and SQLite ledger are server-only. This is a standalone
    policy primitive, not an exposed tool. Identity must be verified upstream.
    """
    if not isinstance(identity, str) or not IDENTITY_PATTERN.fullmatch(identity):
        raise AuthorizationDenied("invalid_identity")
    if not isinstance(nonce, str) or not NONCE_PATTERN.fullmatch(nonce):
        raise AuthorizationDenied("invalid_nonce")
    if type(issued_at) is not int:
        raise AuthorizationDenied("invalid_timestamp")
    if not isinstance(signature, str) or not re.fullmatch(r"[a-f0-9]{64}", signature):
        raise AuthorizationDenied("invalid_signature")
    current = int(time.time()) if now is None else now
    if abs(current - issued_at) > MAX_AGE_SECONDS:
        raise AuthorizationDenied("expired")
    key = os.environ.get("VIA_DISPATCH_APPROVAL_HMAC_KEY", "")
    ledger = os.environ.get("VIA_DISPATCH_NONCE_DB", "")
    if len(key) < 32 or not ledger or not Path(ledger).is_absolute():
        raise AuthorizationDenied("policy_not_configured")
    expected = hmac.new(key.encode(), canonical_message(identity, nonce, issued_at), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AuthorizationDenied("invalid_signature")
    # Atomic insert with UNIQUE constraint; fail closed on DB errors.
    try:
        with sqlite3.connect(ledger, timeout=3) as db:
            db.execute("CREATE TABLE IF NOT EXISTS approvals (nonce TEXT PRIMARY KEY, identity TEXT NOT NULL, issued_at INTEGER NOT NULL)")
            db.execute("INSERT INTO approvals (nonce, identity, issued_at) VALUES (?, ?, ?)", (nonce, identity, issued_at))
    except sqlite3.Error:
        raise AuthorizationDenied("audit_unavailable") from None
    return {"authorized": True, "identity": identity, "nonce": nonce, "repository": REPOSITORY, "workflow": WORKFLOW, "ref": BRANCH}
