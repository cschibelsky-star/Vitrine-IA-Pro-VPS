"""Offline-only signed institutional approval provisioning (HML candidate).

Not exposed by the executor, public MCP, or Unix consumer route.
Only the separate institutional authorization service/operator may invoke it,
with a pinned Ed25519 public key obtained independently from trusted inventory.
A service identity is NOT a human approval: the institution must first verify
the actual approver and the mission authorization in its upstream workflow.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from mission_grant_ledger import LedgerUnavailable

IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SHA = re.compile(r"^[a-f0-9]{40}$")
OPERATIONS = frozenset(("approve", "revoke"))
EXPECTED = frozenset(("operation", "project_id", "tenant_id", "mission_id",
                      "approval_id", "subject", "profile", "source_sha",
                      "expires_at", "issued_at", "nonce"))


class ProvisioningDenied(ValueError):
    pass


def apply_signed_approval(*, db_path: str, raw_payload: bytes,
                          signature: bytes, trusted_public_key: bytes,
                          expected_project: str, expected_tenant: str,
                          pinned_sha: str, now: int | None = None) -> str:
    """Verify trusted signature, then atomically apply an approval or revocation.

    The institution controls signing-key access and upstream permission checks.
    No unsigned or bearer-only pathway exists. This function has no network API.
    """
    if now is None:
        now = int(time.time())
    if type(now) is not int or not db_path or not isinstance(raw_payload, bytes):
        raise ProvisioningDenied("invalid_input")
    if not isinstance(signature, bytes) or not isinstance(trusted_public_key, bytes):
        raise ProvisioningDenied("invalid_signature")
    if len(trusted_public_key) != 32 or len(signature) != 64:
        raise ProvisioningDenied("invalid_signature")
    try:
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(signature, raw_payload)
    except (ValueError, InvalidSignature):
        raise ProvisioningDenied("invalid_signature") from None
    try:
        item: Any = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProvisioningDenied("invalid_payload") from None
    if not isinstance(item, dict) or frozenset(item) != EXPECTED:
        raise ProvisioningDenied("invalid_payload")
    if any(not isinstance(item[k], str) or not IDENT.fullmatch(item[k])
           for k in ("project_id", "tenant_id", "mission_id", "approval_id",
                     "subject", "nonce")):
        raise ProvisioningDenied("invalid_identity")
    if item["operation"] not in OPERATIONS or item["profile"] not in ("probe", "syntax"):
        raise ProvisioningDenied("unsupported_operation")
    if not isinstance(item["source_sha"], str) or not SHA.fullmatch(item["source_sha"]):
        raise ProvisioningDenied("invalid_sha")
    if type(item["issued_at"]) is not int or abs(now - item["issued_at"]) > 90:
        raise ProvisioningDenied("stale_authorization")
    if type(item["expires_at"]) is not int or item["expires_at"] <= now or item["expires_at"] > now + 900:
        raise ProvisioningDenied("invalid_expiry")
    if (item["project_id"], item["tenant_id"], item["source_sha"]) != (
        expected_project, expected_tenant, pinned_sha):
        raise ProvisioningDenied("identity_or_sha_mismatch")
    path = Path(db_path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise LedgerUnavailable("ledger_not_provisioned")
    try:
        con = sqlite3.connect(f"file:{path}?mode=rw", uri=True, isolation_level=None, timeout=3)
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(
                    "INSERT INTO provisioning_nonces (project_id,nonce,used_at) VALUES (?,?,?)",
                    (item["project_id"], item["nonce"], now),
                )
            except sqlite3.IntegrityError as exc:
                raise ProvisioningDenied("provisioning_replayed") from exc
            if item["operation"] == "approve":
                try:
                    con.execute(
                        "INSERT INTO approved_missions VALUES (?,?,?,?,?,?,?,NULL)",
                        (item["mission_id"], item["approval_id"], item["tenant_id"],
                         item["subject"], item["profile"], item["source_sha"], item["expires_at"]),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ProvisioningDenied("approval_already_exists") from exc
            else:
                cursor = con.execute(
                    """UPDATE approved_missions SET revoked_at=?
                       WHERE mission_id=? AND approval_id=? AND tenant_id=?
                         AND subject=? AND profile=? AND source_sha=?
                         AND revoked_at IS NULL""",
                    (now, item["mission_id"], item["approval_id"], item["tenant_id"],
                     item["subject"], item["profile"], item["source_sha"]),
                )
                if cursor.rowcount != 1:
                    raise ProvisioningDenied("approval_not_revocable")
            con.execute("COMMIT")
        except Exception:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()
    except ProvisioningDenied:
        raise
    except sqlite3.Error as exc:
        raise LedgerUnavailable("ledger_unavailable") from exc
    return item["operation"]
