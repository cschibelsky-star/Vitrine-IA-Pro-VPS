from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/connector-release")

BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
TIMEOUT = int(os.getenv("CONNECTOR_RELEASE_TIMEOUT", "60"))
REPOSITORY = os.getenv(
    "CONNECTOR_RELEASE_REPOSITORY",
    "https://github.com/cschibelsky-star/Vitrine-IA-Pro-VPS.git",
)
HELPER_IMAGE = os.getenv("CONNECTOR_RELEASE_HELPER_IMAGE", "vitrine-vps-mcp-ops_broker")
CONNECTOR_ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp")).resolve()
BACKUP_ROOT = Path(os.getenv("CONNECTOR_BACKUP_ROOT", "/srv/backups/vitrine-vps-mcp")).resolve()
LOG_ROOT = Path(os.getenv("CONNECTOR_RELEASE_LOG_ROOT", "/var/log/vitrine-ops/connector-releases")).resolve()
BOOTSTRAP_PATH = "/app/install_connector_release.py"
BRANCH_PATTERN = re.compile(r"^(feature|fix|hotfix|release)/[A-Za-z0-9._/-]+$")


class ConnectorReleaseRequest(BaseModel):
    branch: str
    confirm: str


class ConnectorReleaseStatusRequest(BaseModel):
    job_id: str


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def audit(action: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": "connector-release",
        "action": action,
        "payload": payload,
        "result": result,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(command: list[str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
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


def validate_branch(branch: str) -> str:
    normalized = branch.strip()
    if normalized in {"main", "master", "production", "prod"}:
        raise HTTPException(status_code=403, detail="production_branch_blocked")
    if not BRANCH_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="branch_not_allowed")
    if ".." in normalized or normalized.endswith("/"):
        raise HTTPException(status_code=422, detail="branch_invalid")
    return normalized


def validate_job_id(job_id: str) -> str:
    normalized = job_id.strip()
    if not re.fullmatch(r"connector_release_[0-9]{8}_[0-9]{6}_[a-f0-9]{8}", normalized):
        raise HTTPException(status_code=422, detail="invalid_job_id")
    return normalized


@router.post("/update", dependencies=[Depends(auth)])
def connector_update_release(req: ConnectorReleaseRequest) -> dict[str, Any]:
    if req.confirm != "EXECUTAR":
        raise HTTPException(status_code=422, detail="confirmation_required")

    branch = validate_branch(req.branch)
    if not CONNECTOR_ROOT.is_dir():
        raise HTTPException(status_code=422, detail="connector_root_missing")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = os.urandom(4).hex()
    job_id = f"connector_release_{stamp}_{suffix}"
    log_file = LOG_ROOT / f"{job_id}.log"
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

    command = [
        "docker",
        "run",
        "-d",
        "--name",
        job_id,
        "--restart",
        "no",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-v",
        f"{CONNECTOR_ROOT}:{CONNECTOR_ROOT}:rw",
        "-v",
        f"{BACKUP_ROOT}:{BACKUP_ROOT}:rw",
        "-v",
        f"{LOG_ROOT}:{LOG_ROOT}:rw",
        "-e",
        f"CONNECTOR_RELEASE_LOG={log_file}",
        HELPER_IMAGE,
        "sh",
        "-lc",
        (
            f"python {BOOTSTRAP_PATH} "
            f"--repository {json.dumps(REPOSITORY)} "
            f"--branch {json.dumps(branch)} "
            "--confirm EXECUTAR "
            f"> {json.dumps(str(log_file))} 2>&1"
        ),
    ]
    launch = run(command)
    result = {
        "ok": launch["ok"],
        "job_id": job_id,
        "branch": branch,
        "repository": REPOSITORY,
        "log_file": str(log_file),
        "launch": launch,
        "status": "started" if launch["ok"] else "failed_to_start",
    }
    audit("connector_update_release", {"branch": branch}, result)
    if not launch["ok"]:
        raise HTTPException(status_code=422, detail=result)
    return result


@router.post("/status", dependencies=[Depends(auth)])
def connector_update_status(req: ConnectorReleaseStatusRequest) -> dict[str, Any]:
    job_id = validate_job_id(req.job_id)
    inspect = run([
        "docker",
        "inspect",
        "--format",
        "{{json .State}}",
        job_id,
    ])
    logs = run(["docker", "logs", "--tail", "200", job_id])
    log_file = LOG_ROOT / f"{job_id}.log"
    file_tail = ""
    if log_file.is_file():
        file_tail = log_file.read_text(encoding="utf-8", errors="replace")[-30000:]

    state: dict[str, Any] | None = None
    if inspect["ok"]:
        try:
            state = json.loads(inspect["stdout"].strip())
        except json.JSONDecodeError:
            state = {"raw": inspect["stdout"].strip()}

    running = bool(state and state.get("Running"))
    exit_code = state.get("ExitCode") if state else None
    status = "running" if running else "completed"
    if not running and exit_code not in (None, 0):
        status = "failed"

    result = {
        "ok": inspect["ok"],
        "job_id": job_id,
        "status": status,
        "state": state,
        "container_logs": logs,
        "log_file": str(log_file),
        "log_tail": file_tail,
    }
    audit("connector_update_status", {"job_id": job_id}, result)
    return result
