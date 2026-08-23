from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from project_file_operations import ProjectFileOperationError, safe_project_file
from project_manager_operations import load_manifest, project_paths

router = APIRouter(prefix="/projects")

BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("PROJECT_MANAGER_TIMEOUT", "1200"))
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))


class ProjectReadSafeRequest(BaseModel):
    project_id: str
    path: str
    start_line: int = Field(default=1, ge=1, le=1_000_000)
    end_line: int = Field(default=400, ge=1, le=1_000_000)


class ProjectPatchTextRequest(BaseModel):
    project_id: str
    path: str
    old: str
    new: str
    confirm: str = ""


class ProjectComposeExplicitRequest(BaseModel):
    project_id: str
    compose_file: str
    docker_project: str = ""
    action: str = "status"
    confirm: str = ""


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def audit(action: str, project_id: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": "project-explicit-lab",
        "action": action,
        "project_id": project_id,
        "payload": payload,
        "result": result,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


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


def repository_for(project_id: str) -> Path:
    manifest = load_manifest(project_id)
    _, repository, _ = project_paths(manifest)
    if not repository.is_dir():
        raise HTTPException(status_code=404, detail="repository_not_found")
    return repository


def safe_relative(value: str, detail: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = Path(raw)
    if not raw or path.is_absolute() or ".." in path.parts or raw == ".":
        raise HTTPException(status_code=422, detail=detail)
    return raw


@router.post("/file/read-safe", dependencies=[Depends(auth)])
def project_file_read_safe(req: ProjectReadSafeRequest) -> dict[str, Any]:
    repository = repository_for(req.project_id)
    try:
        relative, candidate = safe_project_file(repository, req.path, must_exist=True)
    except ProjectFileOperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    try:
        lines = candidate.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="file_not_utf8") from exc

    total = len(lines)
    if total == 0:
        start, end, content = 1, 0, ""
    else:
        start = min(req.start_line, total)
        end = min(max(req.end_line, start), total)
        content = "\n".join(lines[start - 1:end])

    return {
        "ok": True,
        "project_id": req.project_id,
        "path": relative,
        "start_line": start,
        "end_line": end,
        "total_lines": total,
        "content": content,
    }


@router.post("/file/patch-text", dependencies=[Depends(auth)])
def project_file_patch_text(req: ProjectPatchTextRequest) -> dict[str, Any]:
    if req.confirm != "EXECUTAR":
        raise HTTPException(status_code=403, detail="confirmation_required")
    if not req.old:
        raise HTTPException(status_code=422, detail="old_text_required")

    repository = repository_for(req.project_id)
    try:
        relative, candidate = safe_project_file(repository, req.path, must_exist=True)
    except ProjectFileOperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    try:
        text = candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="file_not_utf8") from exc

    occurrences = text.count(req.old)
    if occurrences == 0:
        raise HTTPException(status_code=409, detail="old_text_not_found")
    if occurrences > 1:
        raise HTTPException(status_code=409, detail="old_text_not_unique")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = candidate.with_name(f".{candidate.name}.bak-{stamp}")
    shutil.copy2(candidate, backup)
    candidate.write_text(text.replace(req.old, req.new, 1), encoding="utf-8")

    result = {
        "ok": True,
        "project_id": req.project_id,
        "path": relative,
        "backup": backup.relative_to(repository).as_posix(),
        "replacements": 1,
    }
    audit("project_file_patch_text", req.project_id, {"path": relative}, result)
    return result


@router.post("/compose/explicit", dependencies=[Depends(auth)])
def project_compose_explicit(req: ProjectComposeExplicitRequest) -> dict[str, Any]:
    repository = repository_for(req.project_id)
    relative = safe_relative(req.compose_file, "invalid_compose_file")
    compose = (repository / relative).resolve()
    if repository not in compose.parents or not compose.is_file():
        raise HTTPException(status_code=422, detail="invalid_compose_file")

    docker_project = str(req.docker_project or "").strip() or str(
        load_manifest(req.project_id).get("docker", {}).get("project_name", "")
    ).strip()
    if not docker_project:
        docker_project = req.project_id
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in docker_project):
        raise HTTPException(status_code=422, detail="invalid_docker_project")

    action = str(req.action or "status").strip().lower()
    base = ["docker", "compose", "-p", docker_project, "-f", str(compose)]
    if action == "status":
        command = base + ["ps"]
    elif action == "config":
        command = base + ["config"]
    elif action == "up":
        if req.confirm != "EXECUTAR":
            raise HTTPException(status_code=403, detail="confirmation_required")
        command = base + ["up", "-d", "--build"]
    else:
        raise HTTPException(status_code=422, detail="unsupported_compose_action")

    result = run(command, repository)
    response = {
        "ok": result["ok"],
        "project_id": req.project_id,
        "compose_file": relative,
        "docker_project": docker_project,
        "action": action,
        "result": result,
    }
    audit(
        "project_compose_explicit",
        req.project_id,
        {"compose_file": relative, "docker_project": docker_project, "action": action},
        response,
    )
    return response
