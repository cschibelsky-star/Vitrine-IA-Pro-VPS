from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastmcp import FastMCP

VERSION = "0.1.0-bootstrap"
REGISTRY_ROOT = Path(os.getenv("SUPER_REGISTRY_ROOT", "/app/registry/projects")).resolve()
AUDIT_LOG = Path(os.getenv("SUPER_AUDIT_LOG", "/var/log/vitrine-super-ops/audit.jsonl")).resolve()
WORKSPACE_ROOTS = tuple(
    Path(item).resolve()
    for item in os.getenv("SUPER_WORKSPACE_ROOTS", "/srv/projects,/srv/tvsumare").split(",")
    if item.strip()
)

mcp = FastMCP("Vitrine IA Pro - Super Centro Operacional")


def _audit(action: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "payload": payload,
        "result": result,
        "connector": "super-centro-operacional",
        "version": VERSION,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _run(command: list[str], cwd: Path, timeout: int = 300) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-40000:],
            "stderr": proc.stderr[-12000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": 124, "stdout": "", "stderr": "timeout"}
    except OSError as exc:
        return {"ok": False, "exit_code": 127, "stdout": "", "stderr": type(exc).__name__}


def _safe_project_id(project_id: str) -> str:
    value = str(project_id or "").strip().lower()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise ValueError("invalid_project_id")
    return value


def _registry_path(project_id: str) -> Path:
    project_id = _safe_project_id(project_id)
    path = (REGISTRY_ROOT / f"{project_id}.json").resolve()
    if REGISTRY_ROOT not in path.parents:
        raise PermissionError("registry_path_blocked")
    return path


def _load_project(project_id: str) -> dict[str, Any]:
    path = _registry_path(project_id)
    if not path.is_file():
        raise FileNotFoundError("project_not_registered")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("id") != _safe_project_id(project_id):
        raise ValueError("registry_id_mismatch")
    return data


def _repository(project: dict[str, Any]) -> Path:
    workspace = Path(project["workspace"]["root"]).resolve()
    if not any(workspace == root or root in workspace.parents for root in WORKSPACE_ROOTS):
        raise PermissionError("workspace_root_blocked")
    directory = str(project.get("repository", {}).get("directory", "repository"))
    repository = (workspace / directory).resolve()
    if workspace != repository and workspace not in repository.parents:
        raise PermissionError("repository_outside_workspace")
    return repository


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def system_health() -> dict[str, Any]:
    disk = psutil.disk_usage("/")
    result = {
        "ok": True,
        "connector": "vitrine-super-centro-operacional",
        "version": VERSION,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": disk.percent,
        "registered_projects": len(list(REGISTRY_ROOT.glob("*.json"))) if REGISTRY_ROOT.is_dir() else 0,
    }
    _audit("system.health", {}, result)
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_inspect(project_id: str) -> dict[str, Any]:
    try:
        project = _load_project(project_id)
        repository = _repository(project)
        result = {
            "ok": True,
            "project": project,
            "repository_exists": repository.is_dir(),
            "repository_is_git": (repository / ".git").is_dir(),
        }
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
    _audit("project.inspect", {"project_id": project_id}, result)
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def git_status(project_id: str) -> dict[str, Any]:
    project = _load_project(project_id)
    repository = _repository(project)
    result = _run(["git", "status", "--short", "--branch"], repository, timeout=30)
    _audit("git.status", {"project_id": project_id}, {"ok": result.get("ok"), "exit_code": result.get("exit_code")})
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def git_stage(project_id: str, paths: list[str], confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    if not paths:
        return {"ok": False, "error": "paths_required"}
    project = _load_project(project_id)
    repository = _repository(project)
    normalized: list[str] = []
    for raw in paths:
        value = str(raw or "").strip().replace("\\", "/")
        if not value or value.startswith("/") or ".." in value.split("/"):
            return {"ok": False, "error": "invalid_git_path", "path": value}
        normalized.append(value)
    result = _run(["git", "add", "--", *normalized], repository, timeout=60)
    _audit("git.stage", {"project_id": project_id, "paths": normalized}, {"ok": result.get("ok"), "exit_code": result.get("exit_code")})
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def git_commit(project_id: str, message: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    commit_message = str(message or "").strip()
    if not commit_message:
        return {"ok": False, "error": "commit_message_required"}
    project = _load_project(project_id)
    repository = _repository(project)
    result = _run(["git", "commit", "-m", commit_message], repository, timeout=120)
    _audit("git.commit", {"project_id": project_id, "message": commit_message}, {"ok": result.get("ok"), "exit_code": result.get("exit_code")})
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def laravel_test(project_id: str) -> dict[str, Any]:
    project = _load_project(project_id)
    repository = _repository(project)
    if not (repository / "artisan").is_file() or not (repository / "composer.lock").is_file():
        return {"ok": False, "error": "laravel_project_required"}
    result = {
        "ok": False,
        "status": "runner_not_materialized_yet",
        "project_id": project_id,
        "policy": {
            "network": "none",
            "database": "sqlite::memory:",
            "env_source": "synthetic-testing-env",
        },
    }
    _audit("laravel.test", {"project_id": project_id}, result)
    return result


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
