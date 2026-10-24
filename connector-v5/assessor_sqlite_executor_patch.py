"""Restricted Assessor SQLite backup tools for V5, no generic command execution."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from assessor_sqlite_backup import create_backup, restore_isolated, verify

PROJECT = "assessor-online-trial-hml"
CONTAINER = "assessor-online-trial-hml-assessor_app-1"
VOLUME_DB = "assessor-online-trial-hml_assessor_private"
VOLUME_STORAGE = "assessor-online-trial-hml_assessor_storage"
BACKUP_ROOT = Path("/srv/projects/assessor-online-trial-hml/backups/sqlite-g0")
ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

def _id(value: str) -> str:
    if not value or len(value) > 80 or any(c not in ALLOWED for c in value):
        raise ValueError("invalid_backup_id")
    return value

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)

def register(mcp: Any) -> None:
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def assessor_sqlite_g0_backup(project_id: str, backup_id: str, confirm: str = "") -> dict[str, Any]:
        if confirm != "EXECUTAR":
            return {"ok": False, "error": "confirmation_required"}
        if project_id != PROJECT:
            return {"ok": False, "error": "project_not_allowed"}
        try:
            name = _id(backup_id)
            target = BACKUP_ROOT / name
            if target.exists():
                return {"ok": False, "error": "destination_exists"}
            return {"ok": False, "error": "backup_requires_isolated_volume_helper", "project_id": project_id}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def assessor_sqlite_g0_backup_verify(project_id: str, backup_id: str) -> dict[str, Any]:
        if project_id != PROJECT:
            return {"ok": False, "error": "project_not_allowed"}
        try:
            target = BACKUP_ROOT / _id(backup_id)
            if not target.is_dir():
                return {"ok": False, "error": "backup_not_found"}
            return verify(target)
        except (ValueError, OSError, KeyError) as exc:
            return {"ok": False, "error": type(exc).__name__}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def assessor_sqlite_g0_restore_isolated(project_id: str, backup_id: str, restore_id: str, confirm: str = "") -> dict[str, Any]:
        if confirm != "EXECUTAR":
            return {"ok": False, "error": "confirmation_required"}
        if project_id != PROJECT:
            return {"ok": False, "error": "project_not_allowed"}
        try:
            bundle = BACKUP_ROOT / _id(backup_id)
            target = BACKUP_ROOT / "restores" / _id(restore_id)
            if not bundle.is_dir():
                return {"ok": False, "error": "backup_not_found"}
            return restore_isolated(bundle, target)
        except (ValueError, OSError, KeyError) as exc:
            return {"ok": False, "error": type(exc).__name__}
