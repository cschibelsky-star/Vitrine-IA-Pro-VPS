"""MCP wrappers for the optional VIA backup broker endpoints.

Do not register before broker routing, mounts, and auth are validated.
"""
from __future__ import annotations
import os
from typing import Any
import httpx

OPS_BROKER_URL = os.getenv("OPS_BROKER_URL", "http://ops_broker:8770").rstrip("/")
OPS_BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")

def _post(endpoint: str, backup_name: str, expected_sha256: str) -> dict[str, Any]:
    if not OPS_BROKER_TOKEN:
        return {"ok": False, "error": "broker_token_missing"}
    with httpx.Client(timeout=1200) as client:
        response = client.post(
            f"{OPS_BROKER_URL}/via-backup/{endpoint}",
            headers={"Authorization": f"Bearer {OPS_BROKER_TOKEN}"},
            json={"backup_name": backup_name, "expected_sha256": expected_sha256},
        )
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code, "error": "broker_request_rejected"}
    return response.json()

def via_backup_verify(backup_name: str, expected_sha256: str) -> dict[str, Any]:
    """Verify the known VPS backup and inspect VIA member count without extraction."""
    return _post("verify", backup_name, expected_sha256)

def via_backup_restore_isolated(backup_name: str, expected_sha256: str) -> dict[str, Any]:
    """Restore VIA subtree to fixed isolated staging path, never to live VIA."""
    if os.getenv("VIA_ISOLATED_RESTORE_ENABLED") != "true":
        return {"ok": False, "error": "restore_disabled"}
    return _post("restore-isolated", backup_name, expected_sha256)
