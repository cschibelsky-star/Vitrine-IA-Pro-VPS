from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query

router = APIRouter(prefix="/containers")

BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
ALLOWED_CONTAINERS = {
    "vitrine_mcp_v5",
    "vitrine_mcp_v5_recovery_candidate",
    "vitrine_backup",
}


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _allowed(name: str) -> str:
    normalized = str(name or "").strip()
    if normalized not in ALLOWED_CONTAINERS:
        raise HTTPException(status_code=403, detail="container_not_allowed")
    return normalized


def _run(command: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-50000:],
            "stderr": proc.stderr[-20000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": 124, "stdout": "", "stderr": "timeout"}
    except OSError as exc:
        return {"ok": False, "exit_code": 127, "stdout": "", "stderr": type(exc).__name__}


def _audit(action: str, container: str, result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": "container-diagnostics",
        "action": action,
        "container": container,
        "result": {"ok": result.get("ok"), "exit_code": result.get("exit_code")},
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


@router.get("/{name}/status", dependencies=[Depends(auth)])
def container_status(name: str) -> dict[str, Any]:
    container = _allowed(name)
    raw = _run(["docker", "inspect", container], timeout=30)
    if not raw["ok"]:
        result = {"ok": False, "container": container, "error": "container_inspect_failed", "detail": raw}
        _audit("container_status", container, raw)
        return result
    try:
        payload = json.loads(raw["stdout"] or "[]")
        item = payload[0] if isinstance(payload, list) and payload else {}
    except json.JSONDecodeError:
        return {"ok": False, "container": container, "error": "container_inspect_invalid_json"}
    state = item.get("State", {}) or {}
    health = state.get("Health", {}) or {}
    result = {
        "ok": True,
        "container": container,
        "running": bool(state.get("Running")),
        "status": state.get("Status"),
        "health": health.get("Status"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "exit_code": state.get("ExitCode"),
        "restart_count": item.get("RestartCount"),
        "image": item.get("Config", {}).get("Image"),
    }
    _audit("container_status", container, {"ok": True, "exit_code": 0})
    return result


@router.get("/{name}/logs", dependencies=[Depends(auth)])
def container_logs(name: str, tail: int = Query(default=200, ge=1, le=500)) -> dict[str, Any]:
    container = _allowed(name)
    raw = _run(["docker", "logs", "--tail", str(tail), container], timeout=30)
    result = {
        "ok": raw["ok"],
        "container": container,
        "tail": tail,
        "stdout": raw["stdout"],
        "stderr": raw["stderr"],
        "exit_code": raw["exit_code"],
    }
    _audit("container_logs", container, raw)
    return result
