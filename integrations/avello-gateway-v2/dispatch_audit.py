"""Fail-closed persistent dispatch outcome audit; no secrets or request bodies."""
import os
import sqlite3
from pathlib import Path

_ALLOWED = {"accepted_not_verified", "blocked", "dispatch_error"}


class AuditUnavailable(Exception):
    pass


def record(identity: str, nonce: str, outcome: str, reason: str = "") -> None:
    if outcome not in _ALLOWED:
        raise AuditUnavailable("invalid_outcome")
    path = os.environ.get("VIA_DISPATCH_NONCE_DB", "")
    if not path or not Path(path).is_absolute():
        raise AuditUnavailable("audit_not_configured")
    try:
        with sqlite3.connect(path, timeout=3) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS dispatch_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                identity TEXT NOT NULL,
                nonce TEXT NOT NULL,
                outcome TEXT NOT NULL,
                reason TEXT NOT NULL
            )""")
            db.execute("INSERT INTO dispatch_events (identity, nonce, outcome, reason) VALUES (?, ?, ?, ?)",
                       (identity, nonce, outcome, reason[:80]))
    except sqlite3.Error:
        raise AuditUnavailable("audit_unavailable") from None
