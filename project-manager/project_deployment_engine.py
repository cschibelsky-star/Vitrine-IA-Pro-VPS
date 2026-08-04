from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/project-deployments")

MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("PROJECT_MANAGER_TIMEOUT", "1200"))


class DeploymentRequest(BaseModel):
    project_id: str
    environment: str = "homologation"
    update_repository: bool = True
    build: bool = True
    start: bool = True


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def run(command: list[str], cwd: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=TIMEOUT,
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


def audit(project_id: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": "project-deployment-engine",
        "project_id": project_id,
        "payload": payload,
        "result": result,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_manifest(project_id: str) -> dict[str, Any]:
    if not project_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in project_id):
        raise HTTPException(status_code=422, detail="invalid_project_id")
    path = (MANIFEST_ROOT / f"{project_id}.json").resolve()
    if MANIFEST_ROOT not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="manifest_not_found")
    data = json.loads(path.read_text(encoding="utf-8"))
    required = ["id", "workspace_root", "repository", "docker", "deployment"]
    missing = [name for name in required if name not in data]
    if missing:
        raise HTTPException(status_code=422, detail={"missing_manifest_fields": missing})
    return data


def fail(stage: str, steps: list[dict[str, Any]], detail: dict[str, Any]) -> dict[str, Any]:
    return {"ok": False, "stage": stage, "steps": steps, "detail": detail}


@router.post("/deploy", dependencies=[Depends(auth)])
def project_deploy(req: DeploymentRequest) -> dict[str, Any]:
    if req.environment not in {"homologation", "production"}:
        raise HTTPException(status_code=422, detail="invalid_environment")
    if req.environment == "production":
        raise HTTPException(status_code=403, detail="production_requires_explicit_cutover_operation")

    manifest = load_manifest(req.project_id)
    root = Path(manifest["workspace_root"]).resolve()
    repository = root / manifest["repository"].get("directory", "repository")
    compose_file = manifest["docker"].get("compose_file", "docker-compose.yml")
    project_name = manifest["docker"].get("project_name", req.project_id)
    health_url = manifest["deployment"][req.environment]["health_url"]
    steps: list[dict[str, Any]] = []

    if not (repository / ".git").is_dir():
        result = fail("preflight", steps, {"error": "repository_not_cloned", "repository": str(repository)})
        audit(req.project_id, req.model_dump(), result)
        return result

    status = run(["git", "status", "--porcelain"], repository)
    steps.append({"stage": "git_status", "result": status})
    if not status["ok"] or status["stdout"].strip():
        result = fail("git_status", steps, {"error": "worktree_not_clean"})
        audit(req.project_id, req.model_dump(), result)
        return result

    if req.update_repository:
        branch = manifest["repository"].get("branch", "main")
        pull = run(["git", "pull", "--ff-only", "origin", branch], repository)
        steps.append({"stage": "git_pull", "result": pull})
        if not pull["ok"]:
            result = fail("git_pull", steps, pull)
            audit(req.project_id, req.model_dump(), result)
            return result

    if req.build:
        build = run(["docker", "compose", "-p", project_name, "-f", compose_file, "build"], repository)
        steps.append({"stage": "docker_build", "result": build})
        if not build["ok"]:
            result = fail("docker_build", steps, build)
            audit(req.project_id, req.model_dump(), result)
            return result

    if req.start:
        up = run(["docker", "compose", "-p", project_name, "-f", compose_file, "up", "-d"], repository)
        steps.append({"stage": "docker_up", "result": up})
        if not up["ok"]:
            result = fail("docker_up", steps, up)
            audit(req.project_id, req.model_dump(), result)
            return result

    health = run(["curl", "-fsS", "--max-time", "30", health_url], repository)
    steps.append({"stage": "health_check", "result": health})
    result = {
        "ok": health["ok"],
        "project_id": req.project_id,
        "environment": req.environment,
        "health_url": health_url,
        "steps": steps,
    }
    audit(req.project_id, req.model_dump(), result)
    return result
