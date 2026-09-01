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

VERSION = "0.5.5-project-php-runner"
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


def _manifest_path(project_id: str) -> Path:
    project_id = _safe_project_id(project_id)
    path = (MANIFEST_ROOT / f"{project_id}.json").resolve()
    if MANIFEST_ROOT not in path.parents:
        raise PermissionError("manifest_path_blocked")
    return path


def _load_manifest(project_id: str) -> dict[str, Any]:
    project_id = _safe_project_id(project_id)
    path = _manifest_path(project_id)
    if not path.is_file():
        raise FileNotFoundError("manifest_not_found")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("id") != project_id:
        raise ValueError("manifest_id_mismatch")
    return data


def _validated_workspace_root(workspace_root: str) -> Path:
    raw = str(workspace_root or "").strip()
    if not raw or not raw.startswith("/"):
        raise ValueError("invalid_workspace_root")
    workspace = Path(raw).resolve()
    if not any(_within(workspace, root) for root in ALLOWED_WORKSPACE_ROOTS):
        raise PermissionError("workspace_root_blocked")
    return workspace


def _validated_repository_url(url: str) -> str:
    value = str(url or "").strip()
    if value.startswith("https://github.com/") or value.startswith("git@github.com:"):
        return value
    raise ValueError("repository_url_not_allowed")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


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
    except OSError as exc:
        return {"ok": False, "exit_code": 127, "stdout": "", "stderr": type(exc).__name__}


def _runtime_config(manifest: dict[str, Any]) -> tuple[Path, set[str]]:
    runtime = manifest.get("runtime", {})
    if not runtime and manifest.get("id") == "vitrine-ai-pro-factory-hml2":
        runtime = {
            "env_file": ".env.runtime",
            "allowed_keys": ["CORE_AI_HUB_URL", "CENTRO_IA_INTERNAL_TOKEN", "VIA_AI_PROJECT_ID"],
        }
    relative = str(runtime.get("env_file", ".env.runtime")).strip().replace("\\", "/")
    if not relative or relative.startswith("/") or ".." in relative.split("/"):
        raise ValueError("invalid_runtime_env_file")
    allowed = {str(key).strip() for key in runtime.get("allowed_keys", []) if str(key).strip()}
    if not allowed:
        raise PermissionError("runtime_keys_not_configured")
    workspace = Path(str(manifest["workspace_root"])).resolve()
    target = (workspace / relative).resolve()
    if not _within(target, workspace):
        raise PermissionError("runtime_env_outside_workspace")
    return target, allowed


def _parse_env_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    keys: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def _set_env_value(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    replacement = f"{key}={value}"
    found = False
    updated: list[str] = []
    for raw in lines:
        if raw.strip().startswith(f"{key}="):
            if found:
                continue
            updated.append(replacement)
            found = True
        else:
            updated.append(raw)
    if not found:
        updated.append(replacement)
    tmp = path.with_name(f".{path.name}.tmp-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}")
    try:
        tmp.write_text("\n".join(updated).rstrip("\n") + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def connector_health() -> dict[str, Any]:
    projects = sorted(p.stem for p in MANIFEST_ROOT.glob("*.json")) if MANIFEST_ROOT.is_dir() else []
    return {"ok": True, "connector": "vitrine-mcp-v5", "version": VERSION, "architecture": "standalone-fastmcp", "manifest_root": str(MANIFEST_ROOT), "projects": projects}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def system_health() -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    return {"ok": True, "cpu_percent": psutil.cpu_percent(interval=0.1), "memory_percent": psutil.virtual_memory().percent, "disk_percent": round((disk.used / disk.total) * 100, 2), "boot_time": datetime.fromtimestamp(psutil.boot_time(), timezone.utc).isoformat(), "now": datetime.now(timezone.utc).isoformat()}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_context(project_id: str) -> dict[str, Any]:
    manifest, workspace, repository = _project_paths(project_id)
    docker = manifest.get("docker", {})
    return {"ok": True, "project_id": project_id, "name": manifest.get("name", project_id), "workspace_root": str(workspace), "repository_root": str(repository), "repository_url": manifest.get("repository", {}).get("url"), "branch": manifest.get("repository", {}).get("branch", "main"), "compose_file": docker.get("compose_file", ""), "docker_project": docker.get("project_name", project_id)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_manifest(project_id: str) -> dict[str, Any]:
    try:
        return {"ok": True, "manifest": _load_manifest(project_id)}
    except FileNotFoundError:
        return {"ok": False, "error": "manifest_not_found", "project_id": project_id}
    except (ValueError, PermissionError) as exc:
        return {"ok": False, "error": str(exc), "project_id": project_id}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_manifest_create(project_id: str, name: str, workspace_root: str, repository_url: str, branch: str = "main", repository_directory: str = "repository", shared_directories: list[str] | None = None, compose_file: str = "", docker_project: str = "", release_directory: str = "releases", confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    project_id = _safe_project_id(project_id)
    manifest_path = _manifest_path(project_id)
    if manifest_path.exists():
        return {"ok": False, "error": "manifest_already_exists", "project_id": project_id}
    workspace = _validated_workspace_root(workspace_root)
    repo_url = _validated_repository_url(str(repository_url))
    repo_dir = str(repository_directory or "repository").strip().replace("\\", "/")
    release_dir = str(release_directory or "releases").strip().replace("\\", "/")
    if not repo_dir or repo_dir.startswith("/") or ".." in repo_dir.split("/"):
        raise ValueError("invalid_repository_directory")
    if not release_dir or release_dir.startswith("/") or ".." in release_dir.split("/"):
        raise ValueError("invalid_release_directory")
    shared = []
    for item in shared_directories or []:
        value = str(item or "").strip().replace("\\", "/")
        if not value or value.startswith("/") or ".." in value.split("/"):
            raise ValueError("invalid_shared_directory")
        shared.append(value)
    manifest = {
        "id": project_id,
        "name": str(name or project_id).strip() or project_id,
        "workspace_root": str(workspace),
        "repository": {"url": repo_url, "branch": str(branch or "main").strip() or "main", "directory": repo_dir},
        "shared_directories": shared,
        "docker": {"compose_file": str(compose_file or "").strip(), "project_name": str(docker_project or project_id).strip() or project_id},
        "domains": {"homologation": [], "production": []},
        "release": {"directory": release_dir, "exclude": [".git", ".env", "shared", "data", "uploads", "logs", "vendor", "node_modules"]},
    }
    _atomic_write_json(manifest_path, manifest)
    _audit("project_manifest_create", {"project_id": project_id, "workspace_root": str(workspace), "repository_url": repo_url}, {"ok": True, "status": "created"})
    return {"ok": True, "status": "created", "project_id": project_id, "manifest": manifest}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_workspace(project_id: str) -> dict[str, Any]:
    manifest, workspace, repository = _project_paths(project_id)
    return {"ok": True, "project_id": project_id, "workspace_root": str(workspace), "workspace_exists": workspace.is_dir(), "repository_root": str(repository), "repository_exists": repository.is_dir(), "repository_is_git": (repository / ".git").is_dir(), "shared_directories": manifest.get("shared_directories", []), "release_directory": manifest.get("release", {}).get("directory", "releases")}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_clone(project_id: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    manifest, workspace, repository = _project_paths(project_id)
    if repository.exists():
        if (repository / ".git").is_dir():
            return {"ok": True, "status": "already_cloned", "project_id": project_id, "repository_root": str(repository)}
        return {"ok": False, "error": "repository_path_not_git", "repository_root": str(repository)}
    workspace.mkdir(parents=True, exist_ok=True)
    repo_url = _validated_repository_url(str(manifest.get("repository", {}).get("url", "")))
    branch = str(manifest.get("repository", {}).get("branch", "main") or "main")
    result = _run(["git", "clone", "--branch", branch, "--single-branch", repo_url, str(repository)], workspace, timeout=1200)
    result.update({"project_id": project_id, "repository_root": str(repository), "branch": branch})
    _audit("project_clone", {"project_id": project_id, "branch": branch}, {"ok": result.get("ok", False), "exit_code": result.get("exit_code")})
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_status(project_id: str) -> dict[str, Any]:
    _, workspace, repository = _project_paths(project_id)
    is_git = (repository / ".git").is_dir()
    return {"ok": True, "project_id": project_id, "workspace_exists": workspace.exists(), "repository_exists": repository.exists(), "repository_is_git": is_git, "git_status": _run(["git", "status", "--short", "--branch"], repository) if is_git else None, "origin": _run(["git", "remote", "get-url", "origin"], repository) if is_git else None}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_git_status(project_id: str) -> dict[str, Any]:
    _, _, repository = _project_paths(project_id)
    if not (repository / ".git").is_dir():
        return {"ok": False, "error": "repository_not_git"}
    return _run(["git", "status", "--short", "--branch"], repository)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_read_file(project_id: str, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:
    target, relative = _safe_file(project_id, path, True)
    text = target.read_text(encoding="utf-8")
    lines = text.splitlines()
    total = len(lines)
    start = max(1, min(start_line, total or 1))
    end = min(max(end_line, start), total) if total else 0
    return {"ok": True, "project_id": project_id, "path": relative, "start_line": start, "end_line": end, "total_lines": total, "content": "\n".join(lines[start-1:end]) if total else ""}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_file_read_safe(project_id: str, path: str, max_bytes: int = 100000) -> dict[str, Any]:
    target, relative = _safe_file(project_id, path, True)
    limit = min(max(1, int(max_bytes)), MAX_BYTES)
    data = target.read_bytes()
    if len(data) > limit:
        return {"ok": False, "error": "file_too_large", "path": relative, "bytes": len(data), "max_bytes": limit}
    return {"ok": True, "project_id": project_id, "path": relative, "bytes": len(data), "content": data.decode("utf-8")}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_file_patch_text(project_id: str, path: str, old: str, new: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    target, relative = _safe_file(project_id, path, True)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return {"ok": False, "error": "old_text_not_found", "path": relative}
    if count != 1:
        return {"ok": False, "error": "old_text_not_unique", "path": relative, "matches": count}
    backup = target.with_name(f".{target.name}.bak-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}")
    shutil.copy2(target, backup)
    updated = text.replace(old, new, 1)
    tmp = target.with_name(f".{target.name}.tmp-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}")
    try:
        tmp.write_text(updated, encoding="utf-8")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    result = {"ok": True, "status": "patched", "path": relative, "backup": backup.name}
    _audit("project_file_patch_text", {"project_id": project_id, "path": relative}, result)
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_php_lint(project_id: str, path: str) -> dict[str, Any]:
    target, relative = _safe_file(project_id, path, True)
    if target.suffix.lower() != ".php":
        return {"ok": False, "error": "php_file_required", "path": relative}

    manifest, _, repository = _project_paths(project_id)
    local = _run(["php", "-l", str(target)], repository, timeout=30)
    if local.get("exit_code") != 127:
        local.update({"path": relative, "runtime": "connector"})
        _audit("project_php_lint", {"project_id": project_id, "path": relative}, {"ok": local.get("ok", False), "runtime": "connector", "exit_code": local.get("exit_code")})
        return local

    docker_project = str(manifest.get("docker", {}).get("project_name", project_id) or project_id).strip()
    listed = _run([
        "docker", "ps",
        "--filter", f"label=com.docker.compose.project={docker_project}",
        "--format", "{{.Names}}",
    ], repository, timeout=30)
    if not listed.get("ok"):
        return {"ok": False, "error": "php_runtime_discovery_failed", "path": relative, "exit_code": listed.get("exit_code")}

    candidates = [name.strip() for name in str(listed.get("stdout", "")).splitlines() if name.strip()]
    for name in candidates:
        if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in name):
            continue
        inspected = _run(["docker", "inspect", name], repository, timeout=30)
        if not inspected.get("ok"):
            continue
        try:
            payload = json.loads(inspected.get("stdout") or "[]")
            item = payload[0] if isinstance(payload, list) and payload else {}
        except json.JSONDecodeError:
            continue
        if not item.get("State", {}).get("Running"):
            continue
        destination = None
        for mount in item.get("Mounts", []) or []:
            source = str(mount.get("Source") or "")
            if not source:
                continue
            try:
                source_path = Path(source).resolve()
            except OSError:
                continue
            if source_path == repository:
                destination = str(mount.get("Destination") or "").rstrip("/")
                break
        if not destination or not destination.startswith("/"):
            continue
        container_target = f"{destination}/{relative}"
        result = _run(["docker", "exec", "-w", destination, name, "php", "-l", container_target], repository, timeout=30)
        if result.get("exit_code") == 127:
            continue
        result.update({"path": relative, "runtime": "project_container", "container": name})
        _audit("project_php_lint", {"project_id": project_id, "path": relative}, {"ok": result.get("ok", False), "runtime": "project_container", "container": name, "exit_code": result.get("exit_code")})
        return result

    runner_image = os.getenv("PROJECT_PHP_RUNNER_IMAGE", "vitrine-core-hml-app:latest").strip()
    if not runner_image or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/@-" for ch in runner_image):
        result = {"ok": False, "error": "php_runner_image_invalid", "path": relative}
        _audit("project_php_lint", {"project_id": project_id, "path": relative}, result)
        return result

    image_check = _run(["docker", "image", "inspect", runner_image], repository, timeout=30)
    if not image_check.get("ok"):
        result = {"ok": False, "error": "php_runner_image_unavailable", "path": relative, "runtime_image": runner_image}
        _audit("project_php_lint", {"project_id": project_id, "path": relative}, result)
        return result

    result = _run([
        "docker", "run", "--rm",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "64",
        "--memory", "256m",
        "--cpus", "1",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m",
        "--entrypoint", "php",
        "--mount", f"type=bind,src={repository},dst=/project,readonly",
        runner_image,
        "-l", f"/project/{relative}",
    ], repository, timeout=30)
    result.update({"path": relative, "runtime": "ephemeral_container", "runtime_image": runner_image})
    _audit("project_php_lint", {"project_id": project_id, "path": relative}, {"ok": result.get("ok", False), "runtime": "ephemeral_container", "runtime_image": runner_image, "exit_code": result.get("exit_code")})
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_php_validate(project_id: str, operation: str = "tests_marketing") -> dict[str, Any]:
    operation = str(operation or "").strip().lower()
    commands = {
        "tests_marketing": "php artisan test tests/Unit/Marketing --no-interaction",
        "migrate_pretend": "php artisan migrate --pretend --no-interaction",
    }
    if operation not in commands:
        return {"ok": False, "error": "unsupported_php_validation_operation", "allowed": sorted(commands)}

    _, _, repository = _project_paths(project_id)
    if not (repository / "artisan").is_file() or not (repository / "composer.json").is_file():
        return {"ok": False, "error": "laravel_project_required", "operation": operation}

    runner_image = os.getenv("PROJECT_PHP_RUNNER_IMAGE", "vitrine-core-hml-app:latest").strip()
    if not runner_image or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/@-" for ch in runner_image):
        return {"ok": False, "error": "php_runner_image_invalid", "operation": operation}

    image_check = _run(["docker", "image", "inspect", runner_image], repository, timeout=30)
    if not image_check.get("ok"):
        return {"ok": False, "error": "php_runner_image_unavailable", "operation": operation, "runtime_image": runner_image}

    bootstrap = (
        "set -eu; "
        "mkdir -p /work/project; "
        "cp -a /var/www/html/. /work/project/; "
        "cp -a /source/. /work/project/; "
        "cd /work/project; "
        + commands[operation]
    )
    result = _run([
        "docker", "run", "--rm",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "128",
        "--memory", "768m",
        "--cpus", "1",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m",
        "--tmpfs", "/work:rw,nosuid,nodev,size=768m",
        "--env", "APP_ENV=testing",
        "--env", "APP_DEBUG=false",
        "--env", "APP_KEY=base64:MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        "--env", "DB_CONNECTION=sqlite",
        "--env", "DB_DATABASE=:memory:",
        "--env", "CACHE_STORE=array",
        "--env", "SESSION_DRIVER=array",
        "--env", "QUEUE_CONNECTION=sync",
        "--entrypoint", "sh",
        "--mount", f"type=bind,src={repository},dst=/source,readonly",
        runner_image,
        "-lc", bootstrap,
    ], repository, timeout=600)
    result.update({"project_id": project_id, "operation": operation, "runtime": "ephemeral_container", "runtime_image": runner_image})
    _audit("project_php_validate", {"project_id": project_id, "operation": operation}, {"ok": result.get("ok", False), "runtime_image": runner_image, "exit_code": result.get("exit_code")})
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_runtime_config_status(project_id: str) -> dict[str, Any]:
    manifest = _load_manifest(project_id)
    target, allowed = _runtime_config(manifest)
    present = _parse_env_keys(target)
    result = {
        "ok": True,
        "project_id": project_id,
        "runtime_env_file": str(manifest.get("runtime", {}).get("env_file", ".env.runtime")),
        "keys": {key: {"configured": key in present} for key in sorted(allowed)},
    }
    _audit("project_runtime_config_status", {"project_id": project_id}, {"ok": True, "configured_keys": sorted(key for key in allowed if key in present)})
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_runtime_secret_set(project_id: str, key: str, value: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    manifest = _load_manifest(project_id)
    target, allowed = _runtime_config(manifest)
    normalized_key = str(key or "").strip()
    if normalized_key not in allowed:
        return {"ok": False, "error": "runtime_key_not_allowed", "project_id": project_id, "key": normalized_key}
    if "\n" in value or "\r" in value:
        return {"ok": False, "error": "runtime_value_invalid", "project_id": project_id, "key": normalized_key}
    backup_name = None
    if target.is_file():
        backup = target.with_name(f".{target.name}.bak-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}")
        shutil.copy2(target, backup)
        os.chmod(backup, 0o600)
        backup_name = backup.name
    _set_env_value(target, normalized_key, str(value))
    result = {"ok": True, "status": "configured", "project_id": project_id, "key": normalized_key, "backup": backup_name}
    _audit("project_runtime_secret_set", {"project_id": project_id, "key": normalized_key}, {"ok": True, "status": "configured"})
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_compose_explicit(project_id: str, compose_file: str, action: str = "status", docker_project: str = "", confirm: str = "") -> dict[str, Any]:
    target, relative = _safe_file(project_id, compose_file, True)
    _, _, repository = _project_paths(project_id)
    action = str(action or "status").strip().lower()
    project_name = docker_project.strip() or _load_manifest(project_id).get("docker", {}).get("project_name", project_id)
    base = ["docker", "compose", "-p", project_name, "-f", str(target)]
    if action == "status":
        cmd = base + ["ps"]
    elif action == "config":
        cmd = base + ["config", "--no-interpolate"]
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