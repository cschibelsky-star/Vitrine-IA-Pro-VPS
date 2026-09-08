from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastmcp import FastMCP

VERSION = "0.1.1-core-capabilities"
REGISTRY_ROOT = Path(os.getenv("SUPER_REGISTRY_ROOT", "/app/registry/projects")).resolve()
LEGACY_V5_REGISTRY_ROOT = Path(os.getenv("SUPER_LEGACY_V5_REGISTRY_ROOT", "/legacy-v5-manifests")).resolve()
AUDIT_LOG = Path(os.getenv("SUPER_AUDIT_LOG", "/var/log/vitrine-super-ops/audit.jsonl")).resolve()
PHP_RUNNER_IMAGE = os.getenv("SUPER_PHP_RUNNER_IMAGE", "vitrine-core-hml-app:latest").strip()
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


def _run(command: list[str], cwd: Path, timeout: int = 300, input_text: str | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            input=input_text,
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


def _safe_branch(value: str) -> str:
    branch = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
    if not branch or any(ch not in allowed for ch in branch) or branch.startswith("/") or ".." in branch.split("/"):
        raise ValueError("invalid_branch")
    return branch


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


def _normalize_git_paths(paths: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in paths:
        value = str(raw or "").strip().replace("\\", "/")
        if not value or value.startswith("/") or ".." in value.split("/"):
            raise ValueError(f"invalid_git_path:{value}")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _legacy_to_canonical(data: dict[str, Any]) -> dict[str, Any]:
    project_id = _safe_project_id(str(data.get("id", "")))
    repository = data.get("repository", {}) or {}
    docker = data.get("docker", {}) or {}
    runtime = data.get("runtime", {}) or {}
    backup = data.get("backup", {}) or {}
    workspace_root = str(data.get("workspace_root", "")).strip()
    canonical: dict[str, Any] = {
        "id": project_id,
        "name": str(data.get("name") or project_id),
        "repository": {
            "url": str(repository.get("url", "")),
            "branch": str(repository.get("branch", "main") or "main"),
            "directory": str(repository.get("directory", "repository") or "repository"),
        },
        "workspace": {"root": workspace_root},
        "docker": {
            "compose_file": str(docker.get("compose_file", "")),
            "project_name": str(docker.get("project_name", project_id) or project_id),
        },
        "runtime": {
            "env_file": str(runtime.get("env_file", ".env.runtime") or ".env.runtime"),
            "allowed_keys": list(runtime.get("allowed_keys", []) or []),
        },
        "policies": {
            "dirty_tree": "preserve",
            "allow_reset": False,
            "allow_clean": False,
            "backup_before_mutation": bool(backup.get("pre_mutation_required", False)),
        },
    }
    if backup:
        canonical["backup"] = backup
    if data.get("domains"):
        canonical["domains"] = data.get("domains")
    return canonical


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


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def registry_import_v5(confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    if not LEGACY_V5_REGISTRY_ROOT.is_dir():
        return {"ok": False, "error": "legacy_v5_registry_unavailable", "path": str(LEGACY_V5_REGISTRY_ROOT)}
    REGISTRY_ROOT.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []
    skipped: list[dict[str, str]] = []
    for source in sorted(LEGACY_V5_REGISTRY_ROOT.glob("*.json")):
        try:
            legacy = json.loads(source.read_text(encoding="utf-8"))
            canonical = _legacy_to_canonical(legacy)
            target = _registry_path(canonical["id"])
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(canonical, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, target)
            imported.append(canonical["id"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            skipped.append({"file": source.name, "error": type(exc).__name__})
    result = {"ok": not skipped, "imported": imported, "imported_count": len(imported), "skipped": skipped}
    _audit("registry.import_v5", {}, {"ok": result["ok"], "imported_count": len(imported), "skipped_count": len(skipped)})
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


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def git_compare(project_id: str, branch: str = "") -> dict[str, Any]:
    project = _load_project(project_id)
    repository = _repository(project)
    target = _safe_branch(branch or str(project.get("repository", {}).get("branch", "main")))
    fetch = _run(["git", "fetch", "--prune", "origin", f"refs/heads/{target}:refs/remotes/origin/{target}"], repository, timeout=300)
    if not fetch.get("ok"):
        return {"ok": False, "error": "fetch_failed", "detail": fetch}
    local = _run(["git", "rev-parse", "HEAD"], repository, timeout=30)
    remote = _run(["git", "rev-parse", f"origin/{target}"], repository, timeout=30)
    counts = _run(["git", "rev-list", "--left-right", "--count", f"HEAD...origin/{target}"], repository, timeout=30)
    status = _run(["git", "status", "--porcelain=v1"], repository, timeout=30)
    ahead = behind = None
    if counts.get("ok"):
        parts = str(counts.get("stdout", "")).strip().split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])
    result = {
        "ok": bool(local.get("ok") and remote.get("ok") and counts.get("ok")),
        "branch": target,
        "local_head": str(local.get("stdout", "")).strip(),
        "remote_head": str(remote.get("stdout", "")).strip(),
        "ahead": ahead,
        "behind": behind,
        "dirty": bool(str(status.get("stdout", "")).strip()) if status.get("ok") else None,
    }
    _audit("git.compare", {"project_id": project_id, "branch": target}, result)
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def git_stage(project_id: str, paths: list[str], confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    if not paths:
        return {"ok": False, "error": "paths_required"}
    project = _load_project(project_id)
    repository = _repository(project)
    try:
        normalized = _normalize_git_paths(paths)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
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


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def git_preserve(project_id: str, include_untracked_paths: list[str] | None = None, push: bool = True, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    project = _load_project(project_id)
    repository = _repository(project)
    status = _run(["git", "status", "--porcelain=v1"], repository, timeout=30)
    if not status.get("ok"):
        return {"ok": False, "error": "git_status_failed", "detail": status}
    if not str(status.get("stdout", "")).strip():
        return {"ok": True, "status": "clean_no_preservation_needed"}
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], repository, timeout=30)
    untracked_paths = [line.strip() for line in str(untracked.get("stdout", "")).splitlines() if line.strip()]
    explicit_untracked = _normalize_git_paths(include_untracked_paths or [])
    unexpected = [path for path in untracked_paths if path not in explicit_untracked]
    if unexpected:
        return {"ok": False, "error": "untracked_paths_require_explicit_authorization", "untracked": unexpected}
    current = _run(["git", "branch", "--show-current"], repository, timeout=30)
    current_branch = str(current.get("stdout", "")).strip() or "detached"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    preservation = _safe_branch(f"preservation/{project_id}-{stamp}")
    checkout = _run(["git", "checkout", "-b", preservation], repository, timeout=60)
    if not checkout.get("ok"):
        return {"ok": False, "error": "preservation_branch_create_failed", "detail": checkout}
    stage_tracked = _run(["git", "add", "-u"], repository, timeout=60)
    if not stage_tracked.get("ok"):
        return {"ok": False, "error": "preservation_stage_tracked_failed", "branch": preservation, "detail": stage_tracked}
    if explicit_untracked:
        stage_untracked = _run(["git", "add", "--", *explicit_untracked], repository, timeout=60)
        if not stage_untracked.get("ok"):
            return {"ok": False, "error": "preservation_stage_untracked_failed", "branch": preservation, "detail": stage_untracked}
    staged = _run(["git", "diff", "--cached", "--quiet"], repository, timeout=30)
    if staged.get("exit_code") == 0:
        return {"ok": True, "status": "nothing_staged", "branch": preservation, "previous_branch": current_branch}
    commit = _run(["git", "commit", "-m", f"preserve: {project_id} {stamp}"], repository, timeout=120)
    if not commit.get("ok"):
        return {"ok": False, "error": "preservation_commit_failed", "branch": preservation, "detail": commit}
    head = _run(["git", "rev-parse", "HEAD"], repository, timeout=30)
    if push:
        pushed = _run(["git", "push", "-u", "origin", preservation], repository, timeout=300)
        if not pushed.get("ok"):
            return {"ok": False, "error": "preservation_push_failed", "branch": preservation, "head": str(head.get("stdout", "")).strip(), "detail": pushed}
    result = {"ok": True, "status": "preserved", "branch": preservation, "head": str(head.get("stdout", "")).strip(), "previous_branch": current_branch, "pushed": push}
    _audit("git.preserve", {"project_id": project_id, "include_untracked_paths": explicit_untracked, "push": push}, result)
    return result


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def git_push(project_id: str, branch: str = "", confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    project = _load_project(project_id)
    repository = _repository(project)
    if branch:
        target = _safe_branch(branch)
    else:
        current = _run(["git", "branch", "--show-current"], repository, timeout=30)
        target = _safe_branch(str(current.get("stdout", "")).strip())
    result = _run(["git", "push", "-u", "origin", target], repository, timeout=300)
    _audit("git.push", {"project_id": project_id, "branch": target}, {"ok": result.get("ok"), "exit_code": result.get("exit_code")})
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def laravel_test(project_id: str) -> dict[str, Any]:
    project = _load_project(project_id)
    repository = _repository(project)
    if not (repository / "artisan").is_file() or not (repository / "composer.lock").is_file():
        return {"ok": False, "error": "laravel_project_required"}
    if not PHP_RUNNER_IMAGE or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/@-" for ch in PHP_RUNNER_IMAGE):
        return {"ok": False, "error": "php_runner_image_invalid"}
    image_check = _run(["docker", "image", "inspect", PHP_RUNNER_IMAGE], repository, timeout=30)
    if not image_check.get("ok"):
        return {"ok": False, "error": "php_runner_image_unavailable", "runtime_image": PHP_RUNNER_IMAGE}
    lock_hash = hashlib.sha256((repository / "composer.lock").read_bytes()).hexdigest()[:12]
    project_tag = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:8]
    dependency_image = f"vitrine-super-laravel-test:{project_tag}-{lock_hash}"
    dependency_check = _run(["docker", "image", "inspect", dependency_image], repository, timeout=30)
    if not dependency_check.get("ok"):
        dockerfile = (
            f"FROM {PHP_RUNNER_IMAGE}\n"
            "USER root\n"
            "WORKDIR /var/www/html\n"
            "COPY composer.json composer.lock ./\n"
            "RUN composer install --no-interaction --prefer-dist --no-progress --no-scripts --no-plugins\n"
        )
        built = _run(["docker", "build", "-t", dependency_image, "-f", "-", str(repository)], repository, timeout=1200, input_text=dockerfile)
        if not built.get("ok"):
            return {"ok": False, "error": "laravel_test_dependency_build_failed", "detail": built}
    bootstrap = (
        "set -eu; mkdir -p /work/project; "
        "cp -R /var/www/html/. /work/project/; "
        "find /source -mindepth 1 -maxdepth 1 ! -name .git -exec cp -R {} /work/project/ \\;; "
        "cd /work/project; php artisan test --colors=never"
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
        dependency_image,
        "-lc", bootstrap,
    ], repository, timeout=900)
    result.update({"project_id": project_id, "runtime": "ephemeral_container", "runtime_image": dependency_image})
    _audit("laravel.test", {"project_id": project_id}, {"ok": result.get("ok"), "exit_code": result.get("exit_code"), "runtime_image": dependency_image})
    return result


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
