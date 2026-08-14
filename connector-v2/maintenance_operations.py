from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/maintenance")

TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
ROOT = Path(os.getenv("MCP_RUNTIME_ROOT", "/srv/connectors/vitrine-vps-mcp")).resolve()
COMPOSE = ROOT / "docker-compose.mcp.yml"
AUDIT = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
TIMEOUT = int(os.getenv("MCP_MAINTENANCE_TIMEOUT", "1200"))

Action = Literal[
    "status_mcp_connector",
    "restart_mcp_connector",
    "health_mcp_connector",
]


class MaintenanceRequest(BaseModel):
    action: Action
    confirm: str = ""


def _auth(authorization: str | None) -> None:
    if not TOKEN or authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _audit(action: str, result: dict) -> None:
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": "connector-maintenance",
        "action": action,
        "result": result,
    }
    with AUDIT.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _run(command: list[str]) -> dict:
    try:
        proc = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=TIMEOUT,
            check=False,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-20000:],
            "stderr": proc.stderr[-10000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": 124, "stdout": "", "stderr": "timeout"}


def _preflight() -> None:
    if not ROOT.is_dir():
        raise HTTPException(status_code=500, detail="mcp_runtime_root_missing")
    if not COMPOSE.is_file():
        raise HTTPException(status_code=500, detail="mcp_compose_missing")


@router.post("/action")
def maintenance_action(req: MaintenanceRequest, authorization: str | None = Header(default=None)) -> dict:
    _auth(authorization)
    _preflight()

    if req.action == "status_mcp_connector":
        result = _run(["docker", "compose", "-f", str(COMPOSE), "ps", "vps_mcp_connector"])
    elif req.action == "health_mcp_connector":
        result = _run(["docker", "inspect", "-f", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}", "vitrine_vps_mcp_connector"])
    elif req.action == "restart_mcp_connector":
        if req.confirm != "EXECUTAR":
            raise HTTPException(status_code=422, detail="confirmation_required")
        result = _run(["docker", "compose", "-f", str(COMPOSE), "restart", "vps_mcp_connector"])
    else:
        raise HTTPException(status_code=422, detail="unsupported_maintenance_action")

    _audit(req.action, result)
    return {"ok": bool(result.get("ok")), "action": req.action, "result": result}
