from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastmcp import FastMCP

VERSION = "0.5.8-routing-activate"
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
    elif not runtime and manifest.get("id") in {"cursos-ia-bridge-e2e-hml", "cursos-ia-mvp"}:
        runtime = {
            "env_file": ".env.runtime",
            "allowed_keys": ["AI_BROKER_TOKEN", "AI_API_KEY"],
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
def project_manifest_create(project_id: str, name: str, workspace_root: str, repository_url: str, branch: str = "main", repository_directory: str = "repository", shared_directories: list[str] | None = None, compose_file: str = "", docker_project: str = "", release_directory: str = "releases", runtime_env_file: str = ".env.runtime", runtime_allowed_keys: list[str] | None = None, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    project_id = _safe_project_id(project_id)
    manifest_path = _manifest_path(project_id)
    if manifest_path.exists():
        return {"ok": False, "error": "manifest_already_exists", "project_id": project_id}
    workspace = _validated_workspace_root(workspace_root)
    repo_url = _validated_repository_url(repository_url)
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
    runtime_file = str(runtime_env_file or ".env.runtime").strip().replace("\\", "/")
    if not runtime_file or runtime_file.startswith("/") or ".." in runtime_file.split("/"):
        raise ValueError("invalid_runtime_env_file")
    runtime_keys: list[str] = []
    for item in runtime_allowed_keys or []:
        key = str(item or "").strip()
        if not key or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for ch in key) or key[0].isdigit():
            raise ValueError("invalid_runtime_key")
        if key not in runtime_keys:
            runtime_keys.append(key)
    manifest = {
        "id": project_id,
        "name": str(name or project_id).strip() or project_id,
        "workspace_root": str(workspace),
        "repository": {"url": repo_url, "branch": str(branch or "main").strip() or "main", "directory": repo_dir},
        "shared_directories": shared,
        "docker": {"compose_file": str(compose_file or "").strip(), "project_name": str(docker_project or project_id).strip() or project_id},
        "runtime": {"env_file": runtime_file, "allowed_keys": runtime_keys},
        "domains": {"homologation": [], "production": []},
        "release": {"directory": release_dir, "exclude": [".git", ".env", "shared", "data", "uploads", "logs", "vendor", "node_modules"]},
    }
    _atomic_write_json(manifest_path, manifest)
    _audit("project_manifest_create", {"project_id": project_id, "workspace_root": str(workspace), "repository_url": repo_url, "runtime_allowed_keys": runtime_keys}, {"ok": True, "status": "created"})
    return {"ok": True, "status": "created", "project_id": project_id, "manifest": manifest}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_manifest_runtime_configure(project_id: str, runtime_allowed_keys: list[str], runtime_env_file: str = ".env.runtime", confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    project_id = _safe_project_id(project_id)
    manifest_path = _manifest_path(project_id)
    manifest = _load_manifest(project_id)
    runtime_file = str(runtime_env_file or ".env.runtime").strip().replace("\\", "/")
    if not runtime_file or runtime_file.startswith("/") or ".." in runtime_file.split("/"):
        return {"ok": False, "error": "invalid_runtime_env_file", "project_id": project_id}
    runtime_keys: list[str] = []
    for item in runtime_allowed_keys or []:
        key = str(item or "").strip()
        if not key or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for ch in key) or key[0].isdigit():
            return {"ok": False, "error": "invalid_runtime_key", "project_id": project_id, "key": key}
        if key not in runtime_keys:
            runtime_keys.append(key)
    if not runtime_keys:
        return {"ok": False, "error": "runtime_keys_required", "project_id": project_id}
    manifest["runtime"] = {"env_file": runtime_file, "allowed_keys": runtime_keys}
    _atomic_write_json(manifest_path, manifest)
    result = {"ok": True, "status": "configured", "project_id": project_id, "runtime": manifest["runtime"]}
    _audit("project_manifest_runtime_configure", {"project_id": project_id, "runtime_allowed_keys": runtime_keys, "runtime_env_file": runtime_file}, {"ok": True, "status": "configured"})
    return result


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
    result = {"ok": True, "project_id": project_id, "workspace_exists": workspace.exists(), "repository_exists": repository.exists(), "repository_is_git": is_git, "git_status": _run(["git", "status", "--short", "--branch"], repository) if is_git else None, "origin": _run(["git", "remote", "get-url", "origin"], repository) if is_git else None}
    if project_id == "vitrine-ai-social-enterprise":
        container = "studio_app"
        migration_result = _run(["docker", "exec", "-w", "/var/www/html", container, "php", "artisan", "migrate:status", "--no-ansi"], repository, timeout=120)
        stdout = str(migration_result.get("stdout") or "")
        rows: list[dict[str, Any]] = []
        for raw in stdout.splitlines():
            line = raw.strip()
            if not line.startswith("|") or "Migration" in line or set(line) <= {"|", "-", "+", " ", "="}:
                continue
            parts = [part.strip() for part in line.strip("|").split("|")]
            if len(parts) < 3:
                continue
            rows.append({"migration": parts[0], "batch": parts[1], "status": parts[2]})
        result["migration_status"] = {
            "ok": bool(migration_result.get("ok")),
            "container": container,
            "exit_code": migration_result.get("exit_code"),
            "migrations": rows,
            "stdout": stdout[-20000:],
            "stderr": str(migration_result.get("stderr") or "")[-4000:],
        }
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_git_status(project_id: str) -> dict[str, Any]:
    _, _, repository = _project_paths(project_id)
    if not (repository / ".git").is_dir():
        return {"ok": False, "error": "repository_not_git"}
    return _run(["git", "status", "--short", "--branch"], repository)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_git_compare_origin(project_id: str, branch: str = "") -> dict[str, Any]:
    manifest, _, repository = _project_paths(project_id)
    if not (repository / ".git").is_dir():
        return {"ok": False, "error": "repository_not_git"}
    target_branch = str(branch or manifest.get("repository", {}).get("branch", "main") or "main").strip()
    if not target_branch or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-" for ch in target_branch):
        return {"ok": False, "error": "invalid_branch", "branch": target_branch}
    origin = _run(["git", "remote", "get-url", "origin"], repository, timeout=30)
    if not origin.get("ok"):
        return {"ok": False, "error": "origin_unavailable", "detail": origin}
    fetch = _run(["git", "fetch", "--prune", "origin", target_branch], repository, timeout=300)
    if not fetch.get("ok"):
        return {"ok": False, "error": "fetch_failed", "branch": target_branch, "detail": fetch}
    local_head = _run(["git", "rev-parse", "HEAD"], repository, timeout=30)
    remote_head = _run(["git", "rev-parse", f"origin/{target_branch}"], repository, timeout=30)
    counts = _run(["git", "rev-list", "--left-right", "--count", f"HEAD...origin/{target_branch}"], repository, timeout=30)
    status = _run(["git", "status", "--porcelain=v1"], repository, timeout=30)
    ahead = behind = None
    if counts.get("ok"):
        parts = str(counts.get("stdout", "")).strip().split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])
    dirty = bool(str(status.get("stdout", "")).strip()) if status.get("ok") else None
    relation = "unknown"
    if ahead is not None and behind is not None:
        if ahead == 0 and behind == 0:
            relation = "clean" if not dirty else "dirty"
        elif ahead > 0 and behind == 0:
            relation = "ahead"
        elif ahead == 0 and behind > 0:
            relation = "behind"
        else:
            relation = "diverged"
    result = {
        "ok": True,
        "project_id": project_id,
        "branch": target_branch,
        "origin": str(origin.get("stdout", "")).strip(),
        "local_head": str(local_head.get("stdout", "")).strip() if local_head.get("ok") else None,
        "remote_head": str(remote_head.get("stdout", "")).strip() if remote_head.get("ok") else None,
        "ahead": ahead,
        "behind": behind,
        "dirty": dirty,
        "relation": relation,
        "status": str(status.get("stdout", ""))[-20000:],
    }
    _audit("project_git_compare_origin", {"project_id": project_id, "branch": target_branch}, {"ok": True, "relation": relation, "ahead": ahead, "behind": behind, "dirty": dirty})
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_git_reconcile_to_origin(project_id: str, branch: str = "", preservation_branch: str = "", confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    manifest, workspace, repository = _project_paths(project_id)
    if not (repository / ".git").is_dir():
        return {"ok": False, "error": "repository_not_git"}
    target_branch = str(branch or manifest.get("repository", {}).get("branch", "main") or "main").strip()
    preserve = str(preservation_branch or "").strip()
    allowed_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
    if not target_branch or any(ch not in allowed_chars for ch in target_branch):
        return {"ok": False, "error": "invalid_branch", "branch": target_branch}
    if not preserve or any(ch not in allowed_chars for ch in preserve):
        return {"ok": False, "error": "preservation_branch_required"}

    expected_origin = _validated_repository_url(str(manifest.get("repository", {}).get("url", "")))
    origin = _run(["git", "remote", "get-url", "origin"], repository, timeout=30)
    if not origin.get("ok"):
        return {"ok": False, "error": "origin_unavailable", "detail": origin}
    actual_origin = str(origin.get("stdout", "")).strip()
    if actual_origin != expected_origin:
        return {"ok": False, "error": "origin_mismatch", "expected": expected_origin, "actual": actual_origin}

    fetch = _run(["git", "fetch", "--prune", "origin", target_branch], repository, timeout=300)
    if not fetch.get("ok"):
        return {"ok": False, "error": "fetch_failed", "detail": fetch}
    preserve_check = _run(["git", "ls-remote", "--exit-code", "--heads", "origin", f"refs/heads/{preserve}"], repository, timeout=60)
    if not preserve_check.get("ok"):
        return {"ok": False, "error": "preservation_branch_not_found", "preservation_branch": preserve}
    remote_head = _run(["git", "rev-parse", f"origin/{target_branch}"], repository, timeout=30)
    if not remote_head.get("ok"):
        return {"ok": False, "error": "remote_branch_not_found", "branch": target_branch}

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    snapshot = (workspace / "snapshots" / f"git-reconcile-{stamp}").resolve()
    if not _within(snapshot, workspace):
        return {"ok": False, "error": "snapshot_path_blocked"}
    snapshot.mkdir(parents=True, exist_ok=False)
    before_status = _run(["git", "status", "--short", "--branch"], repository, timeout=30)
    before_head = _run(["git", "rev-parse", "HEAD"], repository, timeout=30)
    diff = _run(["git", "diff", "--binary"], repository, timeout=60)
    cached = _run(["git", "diff", "--cached", "--binary"], repository, timeout=60)
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], repository, timeout=30)
    (snapshot / "status.txt").write_text(str(before_status.get("stdout", "")), encoding="utf-8")
    (snapshot / "head.txt").write_text(str(before_head.get("stdout", "")).strip() + "\n", encoding="utf-8")
    (snapshot / "working.patch").write_text(str(diff.get("stdout", "")), encoding="utf-8")
    (snapshot / "cached.patch").write_text(str(cached.get("stdout", "")), encoding="utf-8")
    (snapshot / "untracked.txt").write_text(str(untracked.get("stdout", "")), encoding="utf-8")

    quarantine = (workspace / "quarantine" / f"git-reconcile-{stamp}").resolve()
    moved: list[str] = []
    residual_markers = (".bak-", ".backup-connector-", "backup-connector-", "_smoke_probe.php", "_smoke_result.json", "broker_probe.php", "kairogen_probe.php", "kairogen_provider.php")
    if untracked.get("ok"):
        for raw in str(untracked.get("stdout", "")).splitlines():
            rel = raw.strip().replace("\\", "/")
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                continue
            if not any(marker in rel for marker in residual_markers):
                continue
            source = (repository / rel).resolve()
            if not _within(source, repository) or not source.exists() or source.is_symlink():
                continue
            destination = (quarantine / rel).resolve()
            if not _within(destination, quarantine):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append(rel)

    current_branch = _run(["git", "branch", "--show-current"], repository, timeout=30)
    current_branch_name = str(current_branch.get("stdout", "")).strip() if current_branch.get("ok") else ""
    if current_branch_name != target_branch:
        checkout = _run(["git", "checkout", "-B", target_branch, f"origin/{target_branch}"], repository, timeout=120)
        if not checkout.get("ok"):
            _audit("project_git_reconcile_to_origin", {"project_id": project_id, "branch": target_branch, "preservation_branch": preserve}, {"ok": False, "stage": "checkout", "snapshot": str(snapshot)})
            return {"ok": False, "error": "checkout_failed", "snapshot": str(snapshot), "quarantined": moved, "detail": checkout}
    reset = _run(["git", "reset", "--hard", f"origin/{target_branch}"], repository, timeout=120)
    if not reset.get("ok"):
        _audit("project_git_reconcile_to_origin", {"project_id": project_id, "branch": target_branch, "preservation_branch": preserve}, {"ok": False, "stage": "reset", "snapshot": str(snapshot)})
        return {"ok": False, "error": "reset_failed", "snapshot": str(snapshot), "quarantined": moved, "detail": reset}

    after_head = _run(["git", "rev-parse", "HEAD"], repository, timeout=30)
    after_status = _run(["git", "status", "--short", "--branch"], repository, timeout=30)
    expected_head = str(remote_head.get("stdout", "")).strip()
    actual_head = str(after_head.get("stdout", "")).strip() if after_head.get("ok") else ""
    tracked_dirty = _run(["git", "status", "--porcelain=v1", "--untracked-files=no"], repository, timeout=30)
    ok = bool(after_head.get("ok") and actual_head == expected_head and tracked_dirty.get("ok") and not str(tracked_dirty.get("stdout", "")).strip())
    result = {
        "ok": ok,
        "project_id": project_id,
        "branch": target_branch,
        "preservation_branch": preserve,
        "before_head": str(before_head.get("stdout", "")).strip() if before_head.get("ok") else None,
        "remote_head": expected_head,
        "after_head": actual_head,
        "snapshot": str(snapshot),
        "quarantine": str(quarantine) if moved else None,
        "quarantined": moved,
        "status": str(after_status.get("stdout", ""))[-20000:],
        "tracked_clean": bool(tracked_dirty.get("ok") and not str(tracked_dirty.get("stdout", "")).strip()),
    }
    _audit("project_git_reconcile_to_origin", {"project_id": project_id, "branch": target_branch, "preservation_branch": preserve}, {"ok": ok, "before_head": result["before_head"], "after_head": actual_head, "remote_head": expected_head, "quarantined_count": len(moved), "snapshot": str(snapshot)})
    return result


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

    result = {"ok": False, "error": "php_runtime_not_found", "path": relative, "docker_project": docker_project}
    _audit("project_php_lint", {"project_id": project_id, "path": relative}, result)
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
    if value == "__MIGRATE_EXISTING__":
        if project_id not in {"cursos-ia-bridge-e2e-hml", "cursos-ia-mvp"} or normalized_key != "AI_BROKER_TOKEN":
            return {"ok": False, "error": "runtime_migration_not_allowed", "project_id": project_id, "key": normalized_key}
        inspected = _run(["docker", "inspect", "cursos_ia_mvp_hml"], Path("/"), timeout=30)
        if not inspected.get("ok"):
            return {"ok": False, "error": "runtime_migration_source_unavailable", "project_id": project_id, "key": normalized_key}
        try:
            payload = json.loads(inspected.get("stdout") or "[]")
            item = payload[0] if isinstance(payload, list) and payload else {}
            source_env = item.get("Config", {}).get("Env", []) or []
            source_value = next((entry.split("=", 1)[1] for entry in source_env if entry.startswith(f"{normalized_key}=")), None)
        except (json.JSONDecodeError, IndexError):
            source_value = None
        if source_value is None:
            return {"ok": False, "error": "runtime_migration_key_missing", "project_id": project_id, "key": normalized_key}
        value = source_value
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


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_laravel_migration_status(project_id: str) -> dict[str, Any]:
    if project_id != "vitrine-ai-social-enterprise":
        return {"ok": False, "error": "migration_status_not_allowed_for_project", "project_id": project_id}
    _, _, repository = _project_paths(project_id)
    container = "studio_app"
    inspected = _run(["docker", "inspect", container], repository, timeout=30)
    if not inspected.get("ok"):
        return {"ok": False, "error": "source_runtime_unavailable", "project_id": project_id, "container": container}
    try:
        payload = json.loads(inspected.get("stdout") or "[]")
        item = payload[0] if isinstance(payload, list) and payload else {}
    except json.JSONDecodeError:
        return {"ok": False, "error": "source_runtime_inspect_invalid", "project_id": project_id}
    if not item.get("State", {}).get("Running"):
        return {"ok": False, "error": "source_runtime_not_running", "project_id": project_id, "container": container}
    workdir = "/var/www/html"
    result = _run(["docker", "exec", "-w", workdir, container, "php", "artisan", "migrate:status", "--no-ansi"], repository, timeout=120)
    stdout = str(result.get("stdout") or "")
    rows: list[dict[str, Any]] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line.startswith("|") or "Migration" in line or set(line) <= {"|", "-", "+", " ", "="}:
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < 3:
            continue
        migration, batch, status = parts[0], parts[1], parts[2]
        rows.append({"migration": migration, "batch": batch, "status": status})
    response = {
        "ok": bool(result.get("ok")),
        "project_id": project_id,
        "container": container,
        "exit_code": result.get("exit_code"),
        "migrations": rows,
        "stdout": stdout[-20000:],
        "stderr": str(result.get("stderr") or "")[-4000:],
    }
    _audit("project_laravel_migration_status", {"project_id": project_id}, {"ok": response["ok"], "container": container, "exit_code": response["exit_code"], "migration_count": len(rows)})
    return response


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_laravel_migrate_build1(project_id: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    if project_id != "vitrine-ai-social-enterprise":
        return {"ok": False, "error": "migration_not_allowed_for_project", "project_id": project_id}
    _, _, repository = _project_paths(project_id)
    container = "studio_app"
    migration = "database/migrations/2026_08_31_210500_create_social_entitlements_and_consumption_tables.php"
    inspected = _run(["docker", "inspect", container], repository, timeout=30)
    if not inspected.get("ok"):
        return {"ok": False, "error": "source_runtime_unavailable", "project_id": project_id, "container": container}
    try:
        payload = json.loads(inspected.get("stdout") or "[]")
        item = payload[0] if isinstance(payload, list) and payload else {}
    except json.JSONDecodeError:
        return {"ok": False, "error": "source_runtime_inspect_invalid", "project_id": project_id}
    if not item.get("State", {}).get("Running"):
        return {"ok": False, "error": "source_runtime_not_running", "project_id": project_id, "container": container}
    pre = _run(["docker", "exec", "-w", "/var/www/html", container, "php", "artisan", "migrate:status", "--no-ansi"], repository, timeout=120)
    if not pre.get("ok"):
        return {"ok": False, "error": "migration_status_failed_before", "detail": pre}
    if "2026_08_31_210500_create_social_entitlements_and_consumption_tables" in str(pre.get("stdout") or ""):
        return {"ok": True, "status": "already_ran", "project_id": project_id, "migration": migration}
    result = _run(["docker", "exec", "-w", "/var/www/html", container, "php", "artisan", "migrate", "--path", migration, "--force", "--no-ansi"], repository, timeout=300)
    post = _run(["docker", "exec", "-w", "/var/www/html", container, "php", "artisan", "migrate:status", "--no-ansi"], repository, timeout=120)
    response = {
        "ok": bool(result.get("ok")) and bool(post.get("ok")) and "2026_08_31_210500_create_social_entitlements_and_consumption_tables" in str(post.get("stdout") or ""),
        "status": "migrated" if result.get("ok") else "failed",
        "project_id": project_id,
        "migration": migration,
        "exit_code": result.get("exit_code"),
        "stdout": str(result.get("stdout") or "")[-12000:],
        "stderr": str(result.get("stderr") or "")[-4000:],
        "post_status": str(post.get("stdout") or "")[-12000:],
    }
    _audit("project_laravel_migrate_build1", {"project_id": project_id, "migration": migration}, {"ok": response["ok"], "status": response["status"], "exit_code": response["exit_code"]})
    return response


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_mariadb_backup(project_id: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    if project_id != "vitrine-ai-social-enterprise":
        return {"ok": False, "error": "backup_not_allowed_for_project", "project_id": project_id}
    manifest, workspace, repository = _project_paths(project_id)
    source_container = "studio_app"
    db_container = "vitrine_mariadb"
    inspected = _run(["docker", "inspect", source_container], repository, timeout=30)
    if not inspected.get("ok"):
        return {"ok": False, "error": "source_runtime_unavailable", "detail": inspected}
    try:
        payload = json.loads(inspected.get("stdout") or "[]")
        item = payload[0] if isinstance(payload, list) and payload else {}
        env_items = item.get("Config", {}).get("Env", []) or []
        env_map = {}
        for entry in env_items:
            key, sep, value = str(entry).partition("=")
            if sep:
                env_map[key] = value
    except json.JSONDecodeError:
        return {"ok": False, "error": "source_runtime_inspect_invalid"}
    expected = {
        "DB_CONNECTION": "mysql",
        "DB_HOST": db_container,
        "DB_DATABASE": "vitrine_social",
    }
    for key, value in expected.items():
        if env_map.get(key) != value:
            return {"ok": False, "error": "database_runtime_mismatch", "key": key, "expected": value, "actual": env_map.get(key)}
    username = env_map.get("DB_USERNAME", "")
    password = env_map.get("DB_PASSWORD", "")
    database = env_map.get("DB_DATABASE", "")
    if not username or not password or not database:
        return {"ok": False, "error": "database_credentials_incomplete"}
    backup_dir = (workspace / "backups" / "database").resolve()
    if not _within(backup_dir, workspace):
        return {"ok": False, "error": "backup_path_blocked"}
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"vitrine_social-{stamp}.sql"
    cmd = [
        "docker", "exec", "-e", "MYSQL_PWD", db_container,
        "mariadb-dump", "-u", username,
        "--single-transaction", "--quick", "--routines", "--events", "--triggers",
        "--hex-blob", "--default-character-set=utf8mb4", database,
    ]
    env = {**os.environ, "MYSQL_PWD": password, "LC_ALL": "C.UTF-8"}
    try:
        with target.open("wb") as fh:
            proc = subprocess.run(cmd, cwd=str(repository), stdout=fh, stderr=subprocess.PIPE, timeout=1200, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if target.exists():
            target.unlink()
        return {"ok": False, "error": "database_backup_execution_failed", "detail": type(exc).__name__}
    if proc.returncode != 0:
        if target.exists():
            target.unlink()
        return {"ok": False, "error": "database_backup_failed", "exit_code": proc.returncode, "stderr": proc.stderr.decode("utf-8", errors="replace")[-4000:]}
    size = target.stat().st_size if target.is_file() else 0
    if size < 512:
        if target.exists():
            target.unlink()
        return {"ok": False, "error": "database_backup_too_small", "bytes": size}
    digest = hashlib.sha256()
    with target.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    os.chmod(target, 0o600)
    result = {
        "ok": True,
        "status": "created",
        "project_id": project_id,
        "database": database,
        "backup_path": str(target),
        "bytes": size,
        "sha256": digest.hexdigest(),
    }
    _audit("project_mariadb_backup", {"project_id": project_id, "database": database}, {"ok": True, "backup_path": str(target), "bytes": size, "sha256": result["sha256"]})
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_compose_explicit(project_id: str, compose_file: str, action: str = "status", docker_project: str = "", confirm: str = "") -> dict[str, Any]:
    target, relative = _safe_file(project_id, compose_file, True)
    manifest, _, repository = _project_paths(project_id)
    action = str(action or "status").strip().lower()
    project_name = docker_project.strip() or manifest.get("docker", {}).get("project_name", project_id)
    base = ["docker", "compose"]
    runtime_target = None
    try:
        runtime_target, _ = _runtime_config(manifest)
    except PermissionError as exc:
        if str(exc) != "runtime_keys_not_configured":
            raise
    if runtime_target is not None:
        if not runtime_target.is_file():
            runtime = manifest.get("runtime", {})
            return {"ok": False, "error": "runtime_env_not_configured", "project_id": project_id, "runtime_env_file": str(runtime.get("env_file", ".env.runtime"))}
        base += ["--env-file", str(runtime_target)]
    base += ["-p", project_name, "-f", str(target)]
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


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def activate_hml_route(route_id: str, confirm: str = "") -> dict[str, Any]:
    """Publica uma rota HML previamente cadastrada no registry oficial. Exige confirm='EXECUTAR'."""
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    normalized = str(route_id or "").strip().lower()
    if not normalized or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in normalized):
        return {"ok": False, "error": "invalid_route_id", "route_id": normalized}

    try:
        _, _, routing_repository = _project_paths("vitrine-ia-pro-vps")
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        return {"ok": False, "error": "routing_project_unavailable", "detail": str(exc)}

    registry = routing_repository / "routing" / "routes.json"
    script = routing_repository / "routing" / "activate_single_hml_route.sh"
    if not registry.is_file() or not script.is_file():
        return {"ok": False, "error": "routing_assets_missing", "registry": registry.is_file(), "script": script.is_file()}

    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": "routing_registry_invalid", "detail": type(exc).__name__}

    route = next((item for item in data.get("routes", []) if item.get("id") == normalized), None)
    if route is None:
        return {"ok": False, "error": "route_not_registered", "route_id": normalized}
    if route.get("environment") != "homologation":
        return {"ok": False, "error": "route_environment_not_allowed", "route_id": normalized}
    if route.get("ssl") is not True:
        return {"ok": False, "error": "route_ssl_required", "route_id": normalized}
    if route.get("status") not in {"pending_dns_proxy", "active"}:
        return {"ok": False, "error": "route_status_not_publishable", "route_id": normalized, "status": route.get("status")}

    env = {
        **os.environ,
        "ROUTE_ID": normalized,
        "NGINX_SNI_HOST": "vitrine_nginx",
        "LC_ALL": "C.UTF-8",
    }
    try:
        proc = subprocess.run(
            ["bash", str(script), str(routing_repository)],
            cwd=str(routing_repository),
            text=True,
            capture_output=True,
            timeout=1200,
            check=False,
            env=env,
        )
        result = {
            "ok": proc.returncode == 0,
            "route_id": normalized,
            "hostname": route.get("hostname"),
            "upstream": route.get("upstream"),
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-30000:],
            "stderr": proc.stderr[-10000:],
        }
    except subprocess.TimeoutExpired:
        result = {"ok": False, "error": "route_activation_timeout", "route_id": normalized, "hostname": route.get("hostname")}
    except OSError as exc:
        result = {"ok": False, "error": "route_activation_exec_failed", "route_id": normalized, "detail": type(exc).__name__}

    _audit(
        "activate_hml_route",
        {"route_id": normalized, "hostname": route.get("hostname")},
        {"ok": result.get("ok", False), "exit_code": result.get("exit_code")},
    )
    return result


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
