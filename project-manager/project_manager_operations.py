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
from project_file_operations import (
    ProjectFileOperationError,
    php_lint_project_file,
    safe_project_file as safe_domain_project_file,
    write_project_file,
)

router = APIRouter(prefix="/projects")

MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("PROJECT_MANAGER_TIMEOUT", "1200"))
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
ALLOWED_WORKSPACE_ROOTS = tuple(
    Path(item.strip()).resolve()
    for item in os.getenv(
        "PROJECT_WORKSPACE_ROOTS",
        "/srv/tvsumare,/srv/projects",
    ).split(",")
    if item.strip()
)

DOCKER_ALLOWED_PREFIXES = tuple(
    item.strip()
    for item in os.getenv(
        "PROJECT_DOCKER_ALLOWED_PREFIXES",
        "vitrine_core_,cursos_ia_mvp_,tvsumare_,agente_compras_",
    ).split(",")
    if item.strip()
)
SENSITIVE_ENV_MARKERS = (
    "PASSWORD", "PASSWD", "SECRET", "TOKEN", "API_KEY", "APIKEY",
    "PRIVATE_KEY", "ACCESS_KEY", "AUTH", "CREDENTIAL", "APP_KEY",
)
SAFE_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SAFE_EXEC_BINARIES = {"php", "composer", "npm", "curl", "ffmpeg"}
SAFE_ARTISAN_COMMANDS = {
    "about", "config:show", "route:list", "migrate:status",
    "optimize:clear", "config:clear", "cache:clear", "route:clear", "view:clear", "filament:assets",
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


class ProjectGitStageRequest(BaseModel):
    project_id: str
    paths: list[str]
    confirm: str = ""


class ProjectGitCommitRequest(BaseModel):
    project_id: str
    message: str
    confirm: str = ""


class ProjectGitPushRequest(BaseModel):
    project_id: str
    confirm: str = ""


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


def safe_project_file(
    manifest: dict[str, Any],
    value: Any,
    *,
    must_exist: bool,
) -> tuple[str, Path, Path]:
    _, repository, _ = project_paths(manifest)
    try:
        relative, candidate = safe_domain_project_file(
            repository,
            value,
            must_exist=must_exist,
        )
    except ProjectFileOperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
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
    is_git = (repository / ".git").is_dir()
    status = run(["git", "status", "--short", "--branch"], repository) if is_git else None
    origin = run(["git", "remote", "get-url", "origin"], repository) if is_git else None
    result: dict[str, Any] = {
        "ok": True,
        "project_id": project_id,
        "workspace_exists": root.exists(),
        "repository_exists": repository.exists(),
        "repository_is_git": is_git,
        "git_status": status,
        "origin": origin,
    }
    if not is_git:
        return result

    target_branch = str(manifest["repository"].get("branch", "main") or "main").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
    if not target_branch or any(ch not in allowed for ch in target_branch):
        result["compare_origin"] = {"ok": False, "error": "invalid_branch", "branch": target_branch}
        return result

    fetch = run(["git", "fetch", "--prune", "origin", target_branch], repository)
    if not fetch["ok"]:
        result["compare_origin"] = {"ok": False, "error": "fetch_failed", "branch": target_branch, "detail": fetch}
        return result

    local_head = run(["git", "rev-parse", "HEAD"], repository)
    remote_head = run(["git", "rev-parse", f"origin/{target_branch}"], repository)
    counts = run(["git", "rev-list", "--left-right", "--count", f"HEAD...origin/{target_branch}"], repository)
    porcelain = run(["git", "status", "--porcelain=v1"], repository)
    ahead = behind = None
    if counts["ok"]:
        parts = counts["stdout"].strip().split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])
    dirty = bool(porcelain["stdout"].strip()) if porcelain["ok"] else None
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

    result["compare_origin"] = {
        "ok": True,
        "branch": target_branch,
        "local_head": local_head["stdout"].strip() if local_head["ok"] else None,
        "remote_head": remote_head["stdout"].strip() if remote_head["ok"] else None,
        "ahead": ahead,
        "behind": behind,
        "dirty": dirty,
        "relation": relation,
        "fetch_performed": True,
        "worktree_modified": False,
    }
    audit("project_git_compare_origin", project_id, {"branch": target_branch}, result["compare_origin"])
    return result


@router.post("/git/stage", dependencies=[Depends(auth)])
def project_git_stage_explicit(req: ProjectGitStageRequest) -> dict[str, Any]:
    if req.confirm != "GIT_STAGE":
        raise HTTPException(status_code=409, detail="confirmation_required:GIT_STAGE")
    if not req.paths or len(req.paths) > 200:
        raise HTTPException(status_code=422, detail="git_stage_paths_invalid")

    manifest = load_manifest(req.project_id)
    _, repository, _ = project_paths(manifest)
    if not (repository / ".git").is_dir():
        raise HTTPException(status_code=422, detail="repository_not_git")

    normalized: list[str] = []
    for raw in req.paths:
        value = str(raw).strip()
        candidate = Path(value)
        if (
            not value
            or candidate.is_absolute()
            or ".." in candidate.parts
            or value == "."
            or candidate.parts[0] == ".git"
        ):
            raise HTTPException(status_code=422, detail="invalid_git_stage_path")
        validated_child(repository, value, "git_stage_path")
        normalized.append(candidate.as_posix())

    result = run(["git", "add", "--", *normalized], repository)
    staged = run(["git", "diff", "--cached", "--name-status"], repository)
    outcome = {
        "ok": result["ok"],
        "project_id": req.project_id,
        "paths": normalized,
        "result": result,
        "staged": staged,
    }
    audit("project_git_stage_explicit", req.project_id, {"paths": normalized}, outcome)
    return outcome


@router.post("/git/commit", dependencies=[Depends(auth)])
def project_git_commit_explicit(req: ProjectGitCommitRequest) -> dict[str, Any]:
    if req.confirm != "GIT_COMMIT":
        raise HTTPException(status_code=409, detail="confirmation_required:GIT_COMMIT")

    message = req.message.strip()
    if not message or len(message) > 240 or "\n" in message or "\r" in message:
        raise HTTPException(status_code=422, detail="git_commit_message_invalid")

    manifest = load_manifest(req.project_id)
    _, repository, _ = project_paths(manifest)
    if not (repository / ".git").is_dir():
        raise HTTPException(status_code=422, detail="repository_not_git")

    staged = run(["git", "diff", "--cached", "--name-status"], repository)
    if not staged["ok"]:
        audit("project_git_commit_explicit", req.project_id, {"message": message}, staged)
        return {"ok": False, "project_id": req.project_id, "stage": "staged_read", "result": staged}
    if not staged["stdout"].strip():
        raise HTTPException(status_code=409, detail="nothing_staged")

    commit = run([
        "git",
        "-c", "user.name=Cristian Schibelsky",
        "-c", "user.email=schibelsky69@gmail.com",
        "commit", "-m", message,
    ], repository)
    head = run(["git", "rev-parse", "HEAD"], repository) if commit["ok"] else None
    status = run(["git", "status", "--short", "--branch"], repository)
    outcome = {
        "ok": commit["ok"],
        "project_id": req.project_id,
        "message": message,
        "staged_before_commit": staged,
        "commit": commit,
        "head": head,
        "status": status,
        "push_performed": False,
    }
    audit("project_git_commit_explicit", req.project_id, {"message": message}, outcome)
    return outcome


@router.post("/git/push", dependencies=[Depends(auth)])
def project_git_push_explicit(req: ProjectGitPushRequest) -> dict[str, Any]:
    if req.confirm != "GIT_PUSH":
        raise HTTPException(status_code=409, detail="confirmation_required:GIT_PUSH")

    manifest = load_manifest(req.project_id)
    _, repository, _ = project_paths(manifest)
    if not (repository / ".git").is_dir():
        raise HTTPException(status_code=422, detail="repository_not_git")

    expected_branch = str(manifest["repository"].get("branch", "main")).strip()
    expected_origin = str(manifest["repository"]["url"]).strip()

    current_branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repository)
    if not current_branch["ok"] or current_branch["stdout"].strip() != expected_branch:
        raise HTTPException(status_code=409, detail="git_push_branch_mismatch")

    origin = run(["git", "remote", "get-url", "origin"], repository)
    if not origin["ok"] or origin["stdout"].strip() != expected_origin:
        raise HTTPException(status_code=409, detail="git_push_origin_mismatch")

    fetch = run(["git", "fetch", "origin", expected_branch], repository)
    if not fetch["ok"]:
        outcome = {"ok": False, "project_id": req.project_id, "stage": "fetch", "result": fetch}
        audit("project_git_push_explicit", req.project_id, {"branch": expected_branch}, outcome)
        return outcome

    remote_ref = f"origin/{expected_branch}"
    ff_check = run(["git", "merge-base", "--is-ancestor", remote_ref, "HEAD"], repository)
    if not ff_check["ok"]:
        raise HTTPException(status_code=409, detail="git_push_non_fast_forward")

    push = run(["git", "push", "origin", f"HEAD:refs/heads/{expected_branch}"], repository)
    status = run(["git", "status", "--short", "--branch"], repository)
    outcome = {
        "ok": push["ok"],
        "project_id": req.project_id,
        "branch": expected_branch,
        "origin": expected_origin,
        "push": push,
        "status": status,
        "force": False,
    }
    audit("project_git_push_explicit", req.project_id, {"branch": expected_branch}, outcome)
    return outcome


@router.post("/write-file", dependencies=[Depends(auth)])
def project_write_file(req: ProjectWriteRequest) -> dict[str, Any]:
    try:
        manifest = load_manifest(req.project_id)
        _, repository, _ = project_paths(manifest)
        result = write_project_file(
            repository,
            req.path,
            req.content,
            backup=req.backup,
            confirm=req.confirm,
            audit_callback=lambda payload, outcome: audit(
                "project_write_file",
                req.project_id,
                payload,
                {**outcome, "project_id": req.project_id},
            ),
        )
        result["project_id"] = req.project_id
        return result
    except ProjectFileOperationError as exc:
        http_exc = HTTPException(status_code=exc.status_code, detail=exc.detail)
        _safe_audit_failure("project_write_file", req.project_id, req.path, http_exc)
        raise http_exc from exc
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
        _, repository, _ = project_paths(manifest)
        result = php_lint_project_file(
            repository,
            req.path,
            run_process=subprocess.run,
        )
        result["project_id"] = req.project_id
        audit("project_php_lint", req.project_id, {"path": result["path"]}, result)
        return result
    except ProjectFileOperationError as exc:
        http_exc = HTTPException(status_code=exc.status_code, detail=exc.detail)
        _safe_audit_failure("project_php_lint", req.project_id, req.path, http_exc)
        raise http_exc from exc
    except HTTPException as exc:
        _safe_audit_failure("project_php_lint", req.project_id, req.path, exc)
        raise


class ProjectContainerRequest(BaseModel):
    project_id: str
    container_name: str


class ProjectComposeRmRequest(BaseModel):
    project_id: str
    compose_file: str
    services: list[str]
    docker_project: str = ""
    confirm: str = ""


class ProjectContainerExecRequest(ProjectContainerRequest):
    command: list[str]
    workdir: str = "/var/www/html"
    confirm: str = ""


def run_json(command: list[str], cwd: Path) -> Any:
    result = run(command, cwd)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail={"command_failed": result})
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"invalid_docker_json: {exc}") from exc


def validate_container_name(container_name: str) -> str:
    name = container_name.strip()
    if not SAFE_CONTAINER_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="invalid_container_name")
    if not DOCKER_ALLOWED_PREFIXES or not any(name.startswith(prefix) for prefix in DOCKER_ALLOWED_PREFIXES):
        raise HTTPException(status_code=403, detail="container_not_allowed")
    return name


def redact_container_env(env_items: list[str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for item in env_items:
        key, separator, value = item.partition("=")
        if not separator:
            continue
        upper = key.upper()
        safe[key] = "***REDACTED***" if any(marker in upper for marker in SENSITIVE_ENV_MARKERS) else value
    return safe


def require_confirm(value: str, expected: str) -> None:
    if value != expected:
        raise HTTPException(status_code=409, detail={"confirmation_required": expected})


def validate_exec(command: list[str]) -> tuple[list[str], bool]:
    if not command or len(command) > 20 or any(len(part) > 500 for part in command):
        raise HTTPException(status_code=422, detail="invalid_command")
    binary = command[0]
    if binary not in SAFE_EXEC_BINARIES:
        raise HTTPException(status_code=403, detail="command_not_allowed")
    mutating = False
    if binary == "php" and len(command) >= 3 and command[1] == "artisan":
        artisan = command[2]
        if artisan not in SAFE_ARTISAN_COMMANDS:
            raise HTTPException(status_code=403, detail="artisan_command_not_allowed")
        mutating = artisan in {"optimize:clear", "config:clear", "cache:clear", "route:clear", "view:clear", "filament:assets"}
    elif binary in {"npm", "composer"}:
        allowed = {("npm", "run", "build"), ("npm", "test"), ("npm", "run", "test"),
                   ("composer", "validate"), ("composer", "install")}
        prefix = tuple(command[:3]) if len(command) >= 3 else tuple(command[:2])
        if not any(tuple(command[:len(item)]) == item for item in allowed):
            raise HTTPException(status_code=403, detail="package_command_not_allowed")
        mutating = binary == "composer" and len(command) > 1 and command[1] == "install"
    return command, mutating


@router.post("/compose/rm-explicit", dependencies=[Depends(auth)])
def project_compose_rm_explicit(req: ProjectComposeRmRequest) -> dict[str, Any]:
    if req.confirm != "EXECUTAR":
        raise HTTPException(status_code=403, detail="confirmation_required")

    manifest = load_manifest(req.project_id)
    _, repository, _ = project_paths(manifest)
    relative = str(req.compose_file or "").strip()
    compose = validated_child(repository, relative, "compose_file")
    if not compose.is_file():
        raise HTTPException(status_code=422, detail="invalid_compose_file")

    docker_project = str(req.docker_project or "").strip() or req.project_id
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in docker_project):
        raise HTTPException(status_code=422, detail="invalid_docker_project")

    services = [str(item).strip() for item in req.services if str(item).strip()]
    if not services:
        raise HTTPException(status_code=422, detail="services_required")
    if any(any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in service) for service in services):
        raise HTTPException(status_code=422, detail="invalid_compose_service")

    command = [
        "docker", "compose", "-p", docker_project, "-f", str(compose),
        "rm", "-f", "-s", "-v", *services,
    ]
    result = run(command, repository)
    response = {
        "ok": result["ok"],
        "project_id": req.project_id,
        "compose_file": relative,
        "docker_project": docker_project,
        "services": services,
        "action": "rm",
        "result": result,
    }
    audit(
        "project_compose_rm_explicit",
        req.project_id,
        {"compose_file": relative, "docker_project": docker_project, "services": services},
        response,
    )
    return response


@router.post("/docker/container-info", dependencies=[Depends(auth)])
def project_docker_container_info(req: ProjectContainerRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id)
    root, _, _ = project_paths(manifest)
    name = validate_container_name(req.container_name)
    inspected = run_json(["docker", "inspect", name], root)
    if not isinstance(inspected, list) or not inspected:
        raise HTTPException(status_code=404, detail="container_not_found")

    item = inspected[0]
    networks = item.get("NetworkSettings", {}).get("Networks", {}) or {}
    state = item.get("State", {}) or {}
    logs = run(["docker", "logs", "--tail", "120", name], root)
    log_text = (str(logs.get("stdout", "")) + str(logs.get("stderr", "")))[-12000:]
    log_text = re.sub(
        r"(?i)(password|passwd|secret|token|api[_-]?key|app[_-]?key|authorization)(\s*[=:]\s*)([^\s,;]+)",
        r"\1\2***REDACTED***",
        log_text,
    )
    result = {
        "ok": True,
        "project_id": req.project_id,
        "container": {
            "name": str(item.get("Name", "")).lstrip("/"),
            "image": item.get("Config", {}).get("Image"),
            "status": state.get("Status"),
            "running": bool(state.get("Running")),
            "health": state.get("Health", {}).get("Status"),
            "exit_code": state.get("ExitCode"),
            "error": state.get("Error") or "",
            "oom_killed": bool(state.get("OOMKilled")),
            "restart_count": item.get("RestartCount", 0),
            "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"),
            "networks": {
                network_name: {
                    "ip_address": network_data.get("IPAddress"),
                    "gateway": network_data.get("Gateway"),
                    "aliases": network_data.get("Aliases") or [],
                }
                for network_name, network_data in networks.items()
            },
            "ports": item.get("NetworkSettings", {}).get("Ports", {}) or {},
            "logs_tail": log_text,
        },
    }
    audit("project_docker_container_info", req.project_id, req.model_dump(), result)
    return result


@router.post("/docker/container-env-safe", dependencies=[Depends(auth)])
def project_docker_container_env_safe(req: ProjectContainerRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id)
    root, _, _ = project_paths(manifest)
    name = validate_container_name(req.container_name)
    inspected = run_json(["docker", "inspect", name], root)
    if not isinstance(inspected, list) or not inspected:
        raise HTTPException(status_code=404, detail="container_not_found")

    env_items = inspected[0].get("Config", {}).get("Env", []) or []
    result = {
        "ok": True,
        "project_id": req.project_id,
        "container_name": name,
        "environment": redact_container_env(env_items),
    }
    audit("project_docker_container_env_safe", req.project_id, {"project_id": req.project_id, "container_name": name}, result)
    return result


@router.post("/docker/container-exec", dependencies=[Depends(auth)])
def project_container_exec(req: ProjectContainerExecRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id); root, _, _ = project_paths(manifest); name = validate_container_name(req.container_name)
    command, mutating = validate_exec(req.command)
    if not req.workdir.startswith("/") or ".." in Path(req.workdir).parts: raise HTTPException(status_code=422, detail="invalid_workdir")
    if mutating: require_confirm(req.confirm, "EXECUTE")
    result = run(["docker", "exec", "-w", req.workdir, name, *command], root)
    audit("project_container_exec", req.project_id, req.model_dump(), result); return result
