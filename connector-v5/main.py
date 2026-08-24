from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastmcp import FastMCP

VERSION = "0.5.0-clean"
MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
ALLOWED_WORKSPACE_ROOTS = tuple(Path(p).resolve() for p in os.getenv("PROJECT_WORKSPACE_ROOTS", "/srv/projects,/srv/tvsumare").split(",") if p.strip())
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops-v5/audit.jsonl"))
MAX_BYTES = int(os.getenv("PROJECT_MAX_READ_BYTES", "200000"))
TEXT_SUFFIXES = {".php", ".json", ".md", ".txt", ".yml", ".yaml", ".xml", ".js", ".ts", ".css", ".scss", ".vue", ".sql", ".sh", ".py"}
BLOCKED_NAMES = {".env", "auth.json", "credentials.json", "oauth.json", "id_rsa", "id_ed25519"}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3"}
BLOCKED_DIRS = {".git", "vendor", "node_modules", "__pycache__", "secrets", "credentials", "private", "storage/logs", "storage/oauth"}

mcp = FastMCP("Vitrine IA Pro V5 - Centro Operacional")


def _audit(action: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat(), "connector": "v5", "action": action, "payload": payload, "result": result}
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _safe_project_id(project_id: str) -> str:
    value = str(project_id or "").strip().lower()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise ValueError("invalid_project_id")
    return value


def _load_manifest(project_id: str) -> dict[str, Any]:
    project_id = _safe_project_id(project_id)
    path = (MANIFEST_ROOT / f"{project_id}.json").resolve()
    if MANIFEST_ROOT not in path.parents or not path.is_file():
        raise FileNotFoundError("manifest_not_found")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("id") != project_id:
        raise ValueError("manifest_id_mismatch")
    return data


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _project_paths(project_id: str) -> tuple[dict[str, Any], Path, Path]:
    manifest = _load_manifest(project_id)
    workspace = Path(str(manifest["workspace_root"])).resolve()
    if not any(_within(workspace, root) for root in ALLOWED_WORKSPACE_ROOTS):
        raise PermissionError("workspace_root_blocked")
    repository = (workspace / str(manifest.get("repository", {}).get("directory", "repository"))).resolve()
    if not _within(repository, workspace):
        raise PermissionError("repository_outside_workspace")
    return manifest, workspace, repository


def _normalize_repo_path(path: str) -> str:
    raw = str(path or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if raw.startswith("repository/"):
        raw = raw[len("repository/"):]
    if not raw or raw.startswith("/") or ":" in raw:
        raise ValueError("invalid_project_path")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise ValueError("invalid_project_path")
    return "/".join(parts)


def _safe_file(project_id: str, path: str, must_exist: bool = True) -> tuple[Path, str]:
    _, _, repository = _project_paths(project_id)
    relative = _normalize_repo_path(path)
    candidate = (repository / relative).resolve()
    if not _within(candidate, repository):
        raise PermissionError("project_path_outside_repository")
    low_parts = [p.lower() for p in relative.split("/")]
    joined = "/".join(low_parts)
    name = candidate.name.lower()
    if name in BLOCKED_NAMES or name.startswith(".env") or candidate.suffix.lower() in BLOCKED_SUFFIXES:
        raise PermissionError("sensitive_path_blocked")
    for blocked in BLOCKED_DIRS:
        if joined == blocked or joined.startswith(blocked + "/") or f"/{blocked}/" in f"/{joined}/":
            raise PermissionError("sensitive_path_blocked")
    if candidate.exists() and candidate.is_symlink():
        raise PermissionError("project_symlink_blocked")
    is_compose = name.startswith("docker-compose") and candidate.suffix.lower() in {".yml", ".yaml"}
    is_text = candidate.suffix.lower() in TEXT_SUFFIXES or name.endswith(".blade.php") or name in {"artisan", "composer.json", "composer.lock", "package.json", "package-lock.json", "README.md", "AGENTS.md"} or is_compose
    if not is_text:
        raise PermissionError("non_text_path_blocked")
    if must_exist and not candidate.is_file():
        raise FileNotFoundError("project_file_not_found")
    return candidate, relative


def _run(command: list[str], cwd: Path, timeout: int = 1200) -> dict[str, Any]:
    try:
        proc = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, timeout=timeout, check=False, env={**os.environ, "LC_ALL": "C.UTF-8"})
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": proc.stdout[-50000:], "stderr": proc.stderr[-20000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": 124, "stdout": "", "stderr": "timeout"}


@mcp.tool()
def connector_health() -> dict[str, Any]:
    projects = sorted(p.stem for p in MANIFEST_ROOT.glob("*.json")) if MANIFEST_ROOT.is_dir() else []
    return {"ok": True, "connector": "vitrine-mcp-v5", "version": VERSION, "architecture": "standalone-fastmcp", "manifest_root": str(MANIFEST_ROOT), "projects": projects}


@mcp.tool()
def system_health() -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    return {"ok": True, "cpu_percent": psutil.cpu_percent(interval=0.1), "memory_percent": psutil.virtual_memory().percent, "disk_percent": round((disk.used / disk.total) * 100, 2), "boot_time": datetime.fromtimestamp(psutil.boot_time(), timezone.utc).isoformat(), "now": datetime.now(timezone.utc).isoformat()}


@mcp.tool()
def project_context(project_id: str) -> dict[str, Any]:
    manifest, workspace, repository = _project_paths(project_id)
    docker = manifest.get("docker", {})
    return {"ok": True, "project_id": project_id, "name": manifest.get("name", project_id), "workspace_root": str(workspace), "repository_root": str(repository), "repository_url": manifest.get("repository", {}).get("url"), "branch": manifest.get("repository", {}).get("branch", "main"), "compose_file": docker.get("compose_file", ""), "docker_project": docker.get("project_name", project_id)}


@mcp.tool()
def project_manifest(project_id: str) -> dict[str, Any]:
    return {"ok": True, "manifest": _load_manifest(project_id)}


@mcp.tool()
def project_status(project_id: str) -> dict[str, Any]:
    _, workspace, repository = _project_paths(project_id)
    is_git = (repository / ".git").is_dir()
    return {"ok": True, "project_id": project_id, "workspace_exists": workspace.exists(), "repository_exists": repository.exists(), "repository_is_git": is_git, "git_status": _run(["git", "status", "--short", "--branch"], repository) if is_git else None, "origin": _run(["git", "remote", "get-url", "origin"], repository) if is_git else None}


@mcp.tool()
def project_git_status(project_id: str) -> dict[str, Any]:
    _, _, repository = _project_paths(project_id)
    if not (repository / ".git").is_dir():
        return {"ok": False, "error": "repository_not_git"}
    return _run(["git", "status", "--short", "--branch"], repository)


@mcp.tool()
def project_read_file(project_id: str, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:
    target, relative = _safe_file(project_id, path, True)
    text = target.read_text(encoding="utf-8")
    lines = text.splitlines()
    total = len(lines)
    start = max(1, min(start_line, total or 1))
    end = min(max(end_line, start), total) if total else 0
    return {"ok": True, "project_id": project_id, "path": relative, "start_line": start, "end_line": end, "total_lines": total, "content": "\n".join(lines[start-1:end]) if total else ""}


@mcp.tool()
def project_file_read_safe(project_id: str, path: str, max_bytes: int = 100000) -> dict[str, Any]:
    target, relative = _safe_file(project_id, path, True)
    limit = min(max(1, int(max_bytes)), MAX_BYTES)
    data = target.read_bytes()
    if len(data) > limit:
        return {"ok": False, "error": "file_too_large", "path": relative, "bytes": len(data), "max_bytes": limit}
    return {"ok": True, "project_id": project_id, "path": relative, "bytes": len(data), "content": data.decode("utf-8")}


@mcp.tool()
def project_file_patch_text(project_id: str, path: str, old: str, new: str, confirm: str = "") -> dict[str, Any]:
    target, relative = _safe_file(project_id, path, True)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return {"ok": False, "error": "old_text_not_found", "path": relative}
    if count != 1:
        return {"ok": False, "error": "old_text_not_unique", "path": relative, "matches": count}
    backup = target.with_name(f".{target.name}.bak-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}")
    shutil.copy2(target, backup)
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    result = {"ok": True, "status": "patched", "path": relative, "backup": backup.name}
    _audit("project_file_patch_text", {"project_id": project_id, "path": relative}, result)
    return result


@mcp.tool()
def project_php_lint(project_id: str, path: str) -> dict[str, Any]:
    target, relative = _safe_file(project_id, path, True)
    if target.suffix.lower() != ".php":
        return {"ok": False, "error": "php_file_required", "path": relative}
    _, _, repository = _project_paths(project_id)
    result = _run(["php", "-l", str(target)], repository, timeout=30)
    result["path"] = relative
    return result


@mcp.tool()
def project_compose_explicit(project_id: str, compose_file: str, action: str = "status", docker_project: str = "", confirm: str = "") -> dict[str, Any]:
    target, relative = _safe_file(project_id, compose_file, True)
    _, _, repository = _project_paths(project_id)
    action = str(action or "status").strip().lower()
    project_name = docker_project.strip() or _load_manifest(project_id).get("docker", {}).get("project_name", project_id)
    base = ["docker", "compose", "-p", project_name, "-f", str(target)]
    if action == "status":
        cmd = base + ["ps"]
    elif action == "config":
        cmd = base + ["config"]
    elif action in {"up", "down", "restart", "build", "pull"}:
        if confirm != "EXECUTAR":
            return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR", "action": action}
        cmd = base + (["up", "-d"] if action == "up" else [action])
    else:
        return {"ok": False, "error": "unsupported_compose_action", "action": action}
    result = _run(cmd, repository)
    result.update({"project_id": project_id, "compose_file": relative, "action": action, "docker_project": project_name})
    _audit("project_compose_explicit", {"project_id": project_id, "compose_file": relative, "action": action}, result)
    return result


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
