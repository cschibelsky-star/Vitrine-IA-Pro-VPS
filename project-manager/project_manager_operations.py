from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/projects")

MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("PROJECT_MANAGER_TIMEOUT", "1200"))
PHP_LINT_TIMEOUT = int(os.getenv("PROJECT_PHP_LINT_TIMEOUT", "15"))
MAX_WRITE_BYTES = int(os.getenv("PROJECT_MAX_WRITE_BYTES", "1048576"))
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
ALLOWED_WORKSPACE_ROOTS = tuple(
    Path(item.strip()).resolve()
    for item in os.getenv(
        "PROJECT_WORKSPACE_ROOTS",
        "/srv/tvsumare,/srv/projects",
    ).split(",")
    if item.strip()
)

ALLOWED_PROJECT_ROOTS = {
    "app",
    "bootstrap",
    "config",
    "database",
    "public",
    "resources",
    "routes",
    "storage/app/factory",
    "tests",
}
ALLOWED_PROJECT_FILES = {
    "artisan",
    "composer.json",
    "composer.lock",
    "package.json",
    "package-lock.json",
    "phpunit.xml",
    "vite.config.js",
    "README.md",
    "AGENTS.md",
    "docker-compose.app.yml",
}
TEXT_SUFFIXES = {
    ".php", ".json", ".md", ".txt", ".yml", ".yaml", ".xml",
    ".js", ".ts", ".css", ".scss", ".vue", ".sql", ".sh",
}
BLOCKED_NAMES = {
    ".env", "auth.json", "credentials.json", "oauth.json",
    "id_rsa", "id_ed25519",
}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3"}
SENSITIVE_FRAGMENTS = {"secret", "credential", "oauth", "private"}
BLOCKED_DIRECTORIES = {
    ".git", "vendor", "node_modules", "__pycache__", "bootstrap/cache",
    "storage/framework", "storage/logs", "storage/oauth", "secrets",
    "credentials", "private",
}


class ProjectRequest(BaseModel):
    project_id: str


class ProjectWriteRequest(BaseModel):
    project_id: str
    path: str
    content: str
    backup: bool = True
    confirm: str = ""


class ProjectPathRequest(BaseModel):
    project_id: str
    path: str


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def audit(action: str, project_id: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": "project-manager",
        "action": action,
        "project_id": project_id,
        "payload": payload,
        "result": result,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def validated_workspace_root(value: Any) -> Path:
    root = Path(str(value)).resolve()
    if not any(is_within(root, allowed) for allowed in ALLOWED_WORKSPACE_ROOTS):
        raise HTTPException(status_code=403, detail="workspace_root_blocked")
    return root


def validated_child(root: Path, value: Any, field: str) -> Path:
    raw = str(value).strip()
    candidate_path = Path(raw)
    if not raw or candidate_path.is_absolute() or ".." in candidate_path.parts:
        raise HTTPException(status_code=422, detail=f"invalid_{field}")
    candidate = (root / candidate_path).resolve()
    if not is_within(candidate, root):
        raise HTTPException(status_code=403, detail=f"{field}_outside_workspace")
    return candidate


def _normalize_project_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if (
        not raw
        or raw.startswith(("/", "//"))
        or re.match(r"^[A-Za-z]:/", raw)
        or ":" in raw
        or any(ord(character) < 32 for character in raw)
    ):
        raise HTTPException(status_code=422, detail="invalid_project_path")
    parts = tuple(part for part in raw.split("/") if part not in ("", "."))
    if not parts or ".." in parts or "\x00" in raw:
        raise HTTPException(status_code=422, detail="invalid_project_path")
    return "/".join(parts)


def _is_allowed_project_scope(relative_path: str) -> bool:
    if relative_path in ALLOWED_PROJECT_FILES:
        return True
    return any(
        relative_path == root or relative_path.startswith(root + "/")
        for root in ALLOWED_PROJECT_ROOTS
    )


def _is_sensitive_project_path(relative_path: str, candidate: Path) -> bool:
    parts = [part.lower() for part in relative_path.split("/")]
    name = candidate.name.lower()
    if name in BLOCKED_NAMES or name.startswith(".env") or candidate.suffix.lower() in BLOCKED_SUFFIXES:
        return True
    joined = "/".join(parts)
    if any(fragment in part for part in parts for fragment in SENSITIVE_FRAGMENTS):
        return True
    return any(joined == blocked or joined.startswith(blocked + "/") or f"/{blocked}/" in f"/{joined}/" for blocked in BLOCKED_DIRECTORIES)


def _is_text_path(relative_path: str, candidate: Path) -> bool:
    if relative_path in ALLOWED_PROJECT_FILES:
        return True
    name = candidate.name.lower()
    return name.endswith(".blade.php") or candidate.suffix.lower() in TEXT_SUFFIXES


def _has_symlink_component(repository: Path, relative_path: str) -> bool:
    candidate = repository
    for part in relative_path.split("/"):
        candidate = candidate / part
        if candidate.is_symlink():
            return True
        if not candidate.exists():
            break
    return False


def _sanitize_lint_output(
    output: str,
    repository: Path,
    target: Path,
    relative_path: str,
) -> str:
    sanitized = output.replace(str(target), relative_path)
    sanitized = sanitized.replace(target.as_posix(), relative_path)
    sanitized = sanitized.replace(str(repository), "<project>")
    sanitized = sanitized.replace(repository.as_posix(), "<project>")
    sanitized = "".join(
        character if character in "\n\t" or ord(character) >= 32 else "?"
        for character in sanitized
    )
    return sanitized[-10000:]


def safe_project_file(
    manifest: dict[str, Any],
    value: Any,
    *,
    must_exist: bool,
) -> tuple[str, Path, Path]:
    _, repository, _ = project_paths(manifest)
    relative = _normalize_project_path(value)
    if not _is_allowed_project_scope(relative):
        raise HTTPException(status_code=403, detail="project_path_scope_blocked")
    if _has_symlink_component(repository, relative):
        raise HTTPException(status_code=403, detail="project_symlink_blocked")
    candidate = (repository / relative).resolve()
    if not is_within(candidate, repository):
        raise HTTPException(status_code=403, detail="project_path_outside_repository")
    if _is_sensitive_project_path(relative, candidate):
        raise HTTPException(status_code=403, detail="sensitive_path_blocked")
    if not _is_text_path(relative, candidate):
        raise HTTPException(status_code=403, detail="non_text_path_blocked")
    if must_exist and not candidate.is_file():
        raise HTTPException(status_code=404, detail="project_file_not_found")
    if candidate.exists() and (candidate.is_symlink() or not candidate.is_file()):
        raise HTTPException(status_code=403, detail="project_file_type_blocked")
    return relative, candidate, repository


def _safe_audit_failure(action: str, project_id: str, path: str, exc: HTTPException) -> None:
    audit(action, project_id, {"path": path}, {"ok": False, "detail": exc.detail})


def load_manifest(project_id: str) -> dict[str, Any]:
    if not project_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in project_id):
        raise HTTPException(status_code=422, detail="invalid_project_id")

    path = (MANIFEST_ROOT / f"{project_id}.json").resolve()
    if not is_within(path, MANIFEST_ROOT):
        raise HTTPException(status_code=403, detail="manifest_path_blocked")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="manifest_not_found")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"manifest_invalid: {exc}") from exc

    required = ["id", "workspace_root", "repository", "shared_directories"]
    missing = [key for key in required if key not in data]
    if missing:
        raise HTTPException(status_code=422, detail={"missing_manifest_fields": missing})
    if data["id"] != project_id:
        raise HTTPException(status_code=422, detail="manifest_id_mismatch")
    if not isinstance(data["repository"], dict):
        raise HTTPException(status_code=422, detail="repository_config_invalid")
    if not isinstance(data["shared_directories"], list):
        raise HTTPException(status_code=422, detail="shared_directories_invalid")

    repository = data["repository"]
    if not str(repository.get("url", "")).strip():
        raise HTTPException(status_code=422, detail="repository_url_missing")
    if not str(repository.get("branch", "main")).strip():
        raise HTTPException(status_code=422, detail="repository_branch_invalid")

    root = validated_workspace_root(data["workspace_root"])
    validated_child(root, repository.get("directory", "repository"), "repository_directory")
    validated_child(root, data.get("release", {}).get("directory", "releases"), "release_directory")

    for item in data["shared_directories"]:
        validated_child(root / "shared", item, "shared_directory")

    return data


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


def project_paths(manifest: dict[str, Any]) -> tuple[Path, Path, Path]:
    root = validated_workspace_root(manifest["workspace_root"])
    repository = validated_child(
        root,
        manifest["repository"].get("directory", "repository"),
        "repository_directory",
    )
    releases = validated_child(
        root,
        manifest.get("release", {}).get("directory", "releases"),
        "release_directory",
    )
    return root, repository, releases


def workspace_paths(manifest: dict[str, Any]) -> list[Path]:
    root, repository, releases = project_paths(manifest)
    paths = [root, repository, releases, root / "scripts", root / "snapshots", root / "shared"]
    paths.extend(
        validated_child(root / "shared", item, "shared_directory")
        for item in manifest["shared_directories"]
    )
    return paths


@router.get("/{project_id}/manifest", dependencies=[Depends(auth)])
def project_manifest(project_id: str) -> dict[str, Any]:
    return {"ok": True, "manifest": load_manifest(project_id)}


@router.post("/workspace", dependencies=[Depends(auth)])
def project_workspace(req: ProjectRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id)
    paths = workspace_paths(manifest)
    try:
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)
        result = {
            "ok": True,
            "project_id": req.project_id,
            "paths": [str(path) for path in paths],
        }
    except OSError as exc:
        result = {"ok": False, "project_id": req.project_id, "error": str(exc)}
    audit("project_workspace", req.project_id, req.model_dump(), result)
    return result


@router.post("/clone", dependencies=[Depends(auth)])
def project_clone(req: ProjectRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id)
    root, target, _ = project_paths(manifest)
    repository = manifest["repository"]
    branch = str(repository.get("branch", "main")).strip()
    url = str(repository["url"]).strip()

    root.mkdir(parents=True, exist_ok=True)

    if (target / ".git").is_dir():
        origin = run(["git", "remote", "get-url", "origin"], target)
        if not origin["ok"]:
            result = {"ok": False, "stage": "origin_read", "result": origin}
            audit("project_clone", req.project_id, req.model_dump(), result)
            return result

        current_origin = origin["stdout"].strip()
        if current_origin != url:
            reset_origin = run(["git", "remote", "set-url", "origin", url], target)
            if not reset_origin["ok"]:
                result = {"ok": False, "stage": "origin_reset", "result": reset_origin}
                audit("project_clone", req.project_id, req.model_dump(), result)
                return result

        fetch = run(["git", "fetch", "--all", "--prune"], target)
        if not fetch["ok"]:
            result = {"ok": False, "stage": "fetch", "result": fetch}
            audit("project_clone", req.project_id, req.model_dump(), result)
            return result

        checkout = run(["git", "checkout", branch], target)
        if not checkout["ok"]:
            result = {"ok": False, "stage": "checkout", "result": checkout}
            audit("project_clone", req.project_id, req.model_dump(), result)
            return result

        pull = run(["git", "pull", "--ff-only", "origin", branch], target)
        result = {
            "ok": pull["ok"],
            "operation": "updated",
            "project_id": req.project_id,
            "repository": str(target),
            "origin": url,
            "origin_corrected": current_origin != url,
            "result": pull,
        }
        audit("project_clone", req.project_id, req.model_dump(), result)
        return result

    if target.exists() and any(target.iterdir()):
        result = {
            "ok": False,
            "stage": "preflight",
            "error": "repository_directory_not_empty",
            "repository": str(target),
        }
        audit("project_clone", req.project_id, req.model_dump(), result)
        return result

    if target.exists():
        target.rmdir()

    clone = run(
        ["git", "clone", "--branch", branch, "--single-branch", url, str(target)],
        root,
    )
    result = {
        "ok": clone["ok"],
        "operation": "cloned",
        "project_id": req.project_id,
        "repository": str(target),
        "origin": url,
        "result": clone,
    }
    audit("project_clone", req.project_id, req.model_dump(), result)
    return result


@router.get("/{project_id}/status", dependencies=[Depends(auth)])
def project_status(project_id: str) -> dict[str, Any]:
    manifest = load_manifest(project_id)
    root, repository, _ = project_paths(manifest)
    status = (
        run(["git", "status", "--short", "--branch"], repository)
        if (repository / ".git").is_dir()
        else None
    )
    origin = (
        run(["git", "remote", "get-url", "origin"], repository)
        if (repository / ".git").is_dir()
        else None
    )
    return {
        "ok": True,
        "project_id": project_id,
        "workspace_exists": root.exists(),
        "repository_exists": repository.exists(),
        "repository_is_git": (repository / ".git").is_dir(),
        "git_status": status,
        "origin": origin,
    }


@router.post("/write-file", dependencies=[Depends(auth)])
def project_write_file(req: ProjectWriteRequest) -> dict[str, Any]:
    if req.confirm != "EXECUTAR":
        audit(
            "project_write_file",
            req.project_id,
            {"path": req.path},
            {"ok": False, "detail": "confirmation_required"},
        )
        raise HTTPException(status_code=422, detail="confirmation_required")

    try:
        manifest = load_manifest(req.project_id)
        relative, target, repository = safe_project_file(
            manifest,
            req.path,
            must_exist=False,
        )
        encoded = req.content.encode("utf-8")
        if b"\x00" in encoded:
            raise HTTPException(status_code=422, detail="binary_content_blocked")
        if len(encoded) > MAX_WRITE_BYTES:
            raise HTTPException(status_code=413, detail="content_too_large")

        target.parent.mkdir(parents=True, exist_ok=True)
        if not is_within(target.parent.resolve(), repository):
            raise HTTPException(status_code=403, detail="project_parent_outside_repository")

        backup_relative: str | None = None
        file_mode = 0o644
        if target.is_file():
            file_mode = stat.S_IMODE(target.stat().st_mode)
        if req.backup and target.is_file():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            backup_path = target.with_name(f".{target.name}.bak-{stamp}")
            shutil.copy2(target, backup_path)
            backup_relative = backup_path.relative_to(repository).as_posix()

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.chmod(temporary_path, file_mode)
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        result = {
            "ok": True,
            "status": "written",
            "project_id": req.project_id,
            "path": relative,
            "backup": backup_relative,
            "backup_created": backup_relative is not None,
            "bytes_written": len(encoded),
        }
        audit(
            "project_write_file",
            req.project_id,
            {"path": relative, "backup": req.backup},
            result,
        )
        return result
    except HTTPException as exc:
        _safe_audit_failure("project_write_file", req.project_id, req.path, exc)
        raise
    except OSError as exc:
        audit(
            "project_write_file",
            req.project_id,
            {"path": req.path},
            {"ok": False, "detail": type(exc).__name__},
        )
        raise HTTPException(status_code=500, detail="project_write_failed") from exc


@router.post("/php-lint", dependencies=[Depends(auth)])
def project_php_lint(req: ProjectPathRequest) -> dict[str, Any]:
    try:
        manifest = load_manifest(req.project_id)
        relative, target, repository = safe_project_file(
            manifest,
            req.path,
            must_exist=True,
        )
        if target.suffix.lower() != ".php":
            raise HTTPException(status_code=422, detail="php_file_required")

        try:
            proc = subprocess.run(
                ["php", "-l", str(target)],
                cwd=str(repository),
                shell=False,
                text=True,
                capture_output=True,
                timeout=PHP_LINT_TIMEOUT,
                check=False,
                env={"PATH": os.getenv("PATH", ""), "LC_ALL": "C.UTF-8"},
            )
            output = _sanitize_lint_output(
                proc.stdout + proc.stderr,
                repository,
                target,
                relative,
            )
            success = proc.returncode == 0
            result = {
                "ok": success,
                "project_id": req.project_id,
                "path": relative,
                "success": success,
                "exit_code": proc.returncode,
                "stdout": output,
            }
        except subprocess.TimeoutExpired:
            result = {
                "ok": False,
                "project_id": req.project_id,
                "path": relative,
                "success": False,
                "exit_code": 124,
                "stdout": "timeout",
            }
        except OSError:
            result = {
                "ok": False,
                "project_id": req.project_id,
                "path": relative,
                "success": False,
                "exit_code": 127,
                "stdout": "php_lint_unavailable",
            }

        audit("project_php_lint", req.project_id, {"path": relative}, result)
        return result
    except HTTPException as exc:
        _safe_audit_failure("project_php_lint", req.project_id, req.path, exc)
        raise
