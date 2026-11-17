"""Private HML mission authorization ledger. No HTTP administration interface.

The trusted approval service alone provisions/revokes approved_missions.
The executor can ONLY consume existing grants. An absent/corrupt/unreachable DB
fails closed. For one executor replica, use a persistent writable private mount.
A multi-replica rollout requires an independently reviewed transactional store.
"""
from __future__ import annotations
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Mapping, Any

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SHA = re.compile(r"^[a-f0-9]{40}$")
PROFILES = frozenset(("probe", "syntax"))

class GrantRejected(Exception):
    pass

class LedgerUnavailable(Exception):
    pass

# Apply only through a separate, privileged institutional provisioning service,
# NEVER through a request handler in the executor.
SCHEMA = """
CREATE TABLE approved_missions (
    mission_id TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    profile TEXT NOT NULL,
    source_sha TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    revoked_at INTEGER,
    PRIMARY KEY (mission_id, approval_id)
);
CREATE TABLE consumed_grants (
    jti TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    consumed_at INTEGER NOT NULL,
    UNIQUE (mission_id, approval_id),
    FOREIGN KEY (mission_id, approval_id)
        REFERENCES approved_missions(mission_id, approval_id)
);
"""

def consume_grant(db_path: str, claims: Mapping[str, Any], *, pinned_sha: str,
                  now: int | None = None) -> None:
    """Atomically verify approval + revocation and consume a signed jti.

    Must run AFTER token signature/issuer/audience/scope validation and BEFORE
    any profile action. Rejects duplicates across concurrent requests and
    process restarts when the same persistent database is used.
    """
    if now is None:
        now = int(time.time())
    if type(now) is not int:
        raise GrantRejected("invalid_clock")
    required = ("jti", "mission_id", "approval_id", "tenant_id", "sub",
                "approved_profile", "source_sha")
    if any(not isinstance(claims.get(k), str) or not ID.fullmatch(claims[k])
           for k in required if k != "source_sha"):
        raise GrantRejected("invalid_grant_identity")
    if not isinstance(claims.get("source_sha"), str) or not SHA.fullmatch(claims["source_sha"]):
        raise GrantRejected("invalid_source_sha")
    if not SHA.fullmatch(pinned_sha) or claims["source_sha"] != pinned_sha:
        raise GrantRejected("source_sha_mismatch")
    if claims["approved_profile"] not in PROFILES:
        raise GrantRejected("profile_not_allowed")
    if type(claims.get("exp")) is not int or claims["exp"] <= now:
        raise GrantRejected("expired_grant")

    # No default path, in-memory DB, auto-created DB, or symlinks.
    path = Path(db_path) if db_path else None
    if path is None or not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise LedgerUnavailable("ledger_not_provisioned")
    try:
        con = sqlite3.connect(f"file:{path}?mode=rw", uri=True, timeout=3, isolation_level=None)
        try:
            con.execute("PRAGMA busy_timeout=3000")
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                """SELECT tenant_id,subject,profile,source_sha,expires_at,revoked_at
                     FROM approved_missions WHERE mission_id=? AND approval_id=?""",
                (claims["mission_id"], claims["approval_id"]),
            ).fetchone()
            if row is None:
                raise GrantRejected("approval_not_found")
            tenant, subject, profile, source_sha, expires_at, revoked_at = row
            if revoked_at is not None or type(expires_at) is not int or expires_at <= now:
                raise GrantRejected("approval_revoked_or_expired")
            if (tenant, subject, profile, source_sha) != (
                claims["tenant_id"], claims["sub"], claims["approved_profile"], pinned_sha
            ):
                raise GrantRejected("approval_binding_mismatch")
            try:
                con.execute(
                    """INSERT INTO consumed_grants
                        (jti,mission_id,approval_id,tenant_id,consumed_at)
                        VALUES (?,?,?,?,?)""",
                    (claims["jti"], claims["mission_id"], claims["approval_id"], tenant, now),
                )
            except sqlite3.IntegrityError as exc:
                raise GrantRejected("grant_replayed") from exc
            con.execute("COMMIT")
        except Exception:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()
    except GrantRejected:
        raise
    except sqlite3.Error as exc:
        raise LedgerUnavailable("ledger_unavailable") from exc
