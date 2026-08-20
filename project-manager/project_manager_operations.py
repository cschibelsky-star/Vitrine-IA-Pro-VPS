from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/projects")

MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("PROJECT_MANAGER_TIMEOUT", "1200"))
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
ALLOWED_WORKSPACE_ROOTS = tuple(
    Path(item.strip()).resolve()
    for item in os.getenv("PROJECT_WORKSPACE_ROOTS", "/srv/tvsumare,/srv/projects").split(",")
    if item.strip()
)
DOCKER_ALLOWED_PREFIXES = tuple(
    item.strip()
    for item in os.getenv(
        "PROJECT_DOCKER_ALLOWED_PREFIXES",
        "vitrine_core_,cursos_ia_mvp_,tvsumare_,agente_compras_,via_",
    ).split(",")
    if item.strip()
)
SENSITIVE_ENV_MARKERS = (
    "PASSWORD", "PASSWD", "SECRET", "TOKEN", "API_KEY", "APIKEY",
    "PRIVATE_KEY", "ACCESS_KEY", "AUTH", "CREDENTIAL",
)
SAFE_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SAFE_HOST_RE = re.compile(r"^(127\.0\.0\.1|localhost|[A-Za-z0-9.-]+)$")
SAFE_EXEC_BINARIES = {"php", "node", "npm", "composer", "cat", "ls", "find", "grep", "test"}
SAFE_ARTISAN_COMMANDS = {
    "about", "optimize:clear", "config:clear", "cache:clear", "route:clear", "view:clear",
    "filament:assets", "route:list", "migrate:status",
}
SENSITIVE_FILE_PARTS = {".env", "id_rsa", "id_ed25519", "credentials", "secrets"}


class ProjectRequest(BaseModel):
    project_id: str


class ProjectContainerRequest(BaseModel):
    project_id: str
    container_name: str


class ProjectContainerExecRequest(ProjectContainerRequest):
    command: list[str]
    workdir: str = "/var/www/html"
    confirm: str = ""


class ProjectHttpRequest(BaseModel):
    project_id: str
    url: str
    method: str = "GET"


class ProjectPortRequest(BaseModel):
    project_id: str
    host: str
    port: int


class ProjectComposeExplicitRequest(BaseModel):
    project_id: str
    compose_file: str
    action: str = "status"
    docker_project: str = ""
    confirm: str = ""


class ProjectFileReadRequest(BaseModel):
    project_id: str
    path: str
    max_bytes: int = 100000


class ProjectFilePatchRequest(BaseModel):
    project_id: str
    path: str
    old: str
    new: str
    confirm: str = ""


class ProjectManifestRepositoryUpdateRequest(BaseModel):
    project_id: str
    url: str
    branch: str
    confirm: str = ""


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def audit(action: str, project_id: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = dict(payload)
    if "confirm" in safe_payload:
        safe_payload["confirm"] = "***"
    record = {
        "at": datetime.now(timezone.utc).isoformat(), "scope": "project-manager",
        "action": action, "project_id": project_id, "payload": safe_payload, "result": result,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def require_confirm(value: str, expected: str) -> None:
    if value != expected:
        raise HTTPException(status_code=409, detail={"confirmation_required": expected})


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


def manifest_path(project_id: str) -> Path:
    if not project_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in project_id):
        raise HTTPException(status_code=422, detail="invalid_project_id")
    path = (MANIFEST_ROOT / f"{project_id}.json").resolve()
    if not is_within(path, MANIFEST_ROOT):
        raise HTTPException(status_code=403, detail="manifest_path_blocked")
    return path


def load_manifest(project_id: str) -> dict[str, Any]:
    path = manifest_path(project_id)
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
    if data["id"] != project_id or not isinstance(data["repository"], dict) or not isinstance(data["shared_directories"], list):
        raise HTTPException(status_code=422, detail="manifest_structure_invalid")
    repository = data["repository"]
    if not str(repository.get("url", "")).strip() or not str(repository.get("branch", "main")).strip():
        raise HTTPException(status_code=422, detail="repository_config_invalid")
    root = validated_workspace_root(data["workspace_root"])
    validated_child(root, repository.get("directory", "repository"), "repository_directory")
    validated_child(root, data.get("release", {}).get("directory", "releases"), "release_directory")
    for item in data["shared_directories"]:
        validated_child(root / "shared", item, "shared_directory")
    return data


def run(command: list[str], cwd: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, timeout=TIMEOUT,
                              check=False, env={**os.environ, "LC_ALL": "C.UTF-8"})
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode,
                "stdout": proc.stdout[-50000:], "stderr": proc.stderr[-20000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": 124, "stdout": "", "stderr": "timeout"}


def run_json(command: list[str], cwd: Path) -> Any:
    result = run(command, cwd)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail={"command_failed": result})
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"invalid_docker_json: {exc}") from exc


def project_paths(manifest: dict[str, Any]) -> tuple[Path, Path, Path]:
    root = validated_workspace_root(manifest["workspace_root"])
    repository = validated_child(root, manifest["repository"].get("directory", "repository"), "repository_directory")
    releases = validated_child(root, manifest.get("release", {}).get("directory", "releases"), "release_directory")
    return root, repository, releases


def workspace_paths(manifest: dict[str, Any]) -> list[Path]:
    root, repository, releases = project_paths(manifest)
    paths = [root, repository, releases, root / "scripts", root / "snapshots", root / "shared"]
    paths.extend(validated_child(root / "shared", item, "shared_directory") for item in manifest["shared_directories"])
    return paths


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
        if separator:
            safe[key] = "***REDACTED***" if any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS) else value
    return safe


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


def safe_project_file(repository: Path, relative: str) -> Path:
    path = validated_child(repository, relative, "file_path")
    lowered = {part.lower() for part in path.parts}
    if any(marker.lower() in lowered for marker in SENSITIVE_FILE_PARTS):
        raise HTTPException(status_code=403, detail="sensitive_file_blocked")
    return path


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
        result = {"ok": True, "project_id": req.project_id, "paths": [str(path) for path in paths]}
    except OSError as exc:
        result = {"ok": False, "project_id": req.project_id, "error": str(exc)}
    audit("project_workspace", req.project_id, req.model_dump(), result)
    return result


@router.post("/clone", dependencies=[Depends(auth)])
def project_clone(req: ProjectRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id)
    root, target, _ = project_paths(manifest)
    repository = manifest["repository"]
    branch, url = str(repository.get("branch", "main")).strip(), str(repository["url"]).strip()
    root.mkdir(parents=True, exist_ok=True)
    if (target / ".git").is_dir():
        origin = run(["git", "remote", "get-url", "origin"], target)
        if not origin["ok"]:
            result = {"ok": False, "stage": "origin_read", "result": origin}; audit("project_clone", req.project_id, req.model_dump(), result); return result
        current_origin = origin["stdout"].strip()
        if current_origin != url:
            reset_origin = run(["git", "remote", "set-url", "origin", url], target)
            if not reset_origin["ok"]:
                result = {"ok": False, "stage": "origin_reset", "result": reset_origin}; audit("project_clone", req.project_id, req.model_dump(), result); return result
        for stage, cmd in (("fetch", ["git", "fetch", "--all", "--prune"]), ("checkout", ["git", "checkout", branch])):
            outcome = run(cmd, target)
            if not outcome["ok"]:
                result = {"ok": False, "stage": stage, "result": outcome}; audit("project_clone", req.project_id, req.model_dump(), result); return result
        pull = run(["git", "pull", "--ff-only", "origin", branch], target)
        result = {"ok": pull["ok"], "operation": "updated", "project_id": req.project_id, "repository": str(target),
                  "origin": url, "origin_corrected": current_origin != url, "result": pull}
        audit("project_clone", req.project_id, req.model_dump(), result); return result
    if target.exists() and any(target.iterdir()):
        result = {"ok": False, "stage": "preflight", "error": "repository_directory_not_empty", "repository": str(target)}
        audit("project_clone", req.project_id, req.model_dump(), result); return result
    if target.exists(): target.rmdir()
    clone = run(["git", "clone", "--branch", branch, "--single-branch", url, str(target)], root)
    result = {"ok": clone["ok"], "operation": "cloned", "project_id": req.project_id, "repository": str(target), "origin": url, "result": clone}
    audit("project_clone", req.project_id, req.model_dump(), result); return result


@router.get("/{project_id}/status", dependencies=[Depends(auth)])
def project_status(project_id: str) -> dict[str, Any]:
    manifest = load_manifest(project_id); root, repository, _ = project_paths(manifest)
    status = run(["git", "status", "--short", "--branch"], repository) if (repository / ".git").is_dir() else None
    origin = run(["git", "remote", "get-url", "origin"], repository) if (repository / ".git").is_dir() else None
    return {"ok": True, "project_id": project_id, "workspace_exists": root.exists(), "repository_exists": repository.exists(),
            "repository_is_git": (repository / ".git").is_dir(), "git_status": status, "origin": origin}


@router.post("/docker/container-info", dependencies=[Depends(auth)])
def project_docker_container_info(req: ProjectContainerRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id); root, _, _ = project_paths(manifest); name = validate_container_name(req.container_name)
    inspected = run_json(["docker", "inspect", name], root)
    if not isinstance(inspected, list) or not inspected: raise HTTPException(status_code=404, detail="container_not_found")
    item = inspected[0]; networks = item.get("NetworkSettings", {}).get("Networks", {}) or {}
    result = {"ok": True, "project_id": req.project_id, "container": {"name": str(item.get("Name", "")).lstrip("/"),
              "image": item.get("Config", {}).get("Image"), "status": item.get("State", {}).get("Status"),
              "running": bool(item.get("State", {}).get("Running")), "health": item.get("State", {}).get("Health", {}).get("Status"),
              "networks": {n: {"ip_address": d.get("IPAddress"), "gateway": d.get("Gateway"), "aliases": d.get("Aliases") or []} for n, d in networks.items()},
              "ports": item.get("NetworkSettings", {}).get("Ports", {}) or {}}}
    audit("project_docker_container_info", req.project_id, req.model_dump(), result); return result


@router.post("/docker/container-env-safe", dependencies=[Depends(auth)])
def project_docker_container_env_safe(req: ProjectContainerRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id); root, _, _ = project_paths(manifest); name = validate_container_name(req.container_name)
    inspected = run_json(["docker", "inspect", name], root)
    if not isinstance(inspected, list) or not inspected: raise HTTPException(status_code=404, detail="container_not_found")
    result = {"ok": True, "project_id": req.project_id, "container_name": name,
              "environment": redact_container_env(inspected[0].get("Config", {}).get("Env", []) or [])}
    audit("project_docker_container_env_safe", req.project_id, {"project_id": req.project_id, "container_name": name}, result); return result


@router.post("/docker/container-exec", dependencies=[Depends(auth)])
def project_container_exec(req: ProjectContainerExecRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id); root, _, _ = project_paths(manifest); name = validate_container_name(req.container_name)
    command, mutating = validate_exec(req.command)
    if not req.workdir.startswith("/") or ".." in Path(req.workdir).parts: raise HTTPException(status_code=422, detail="invalid_workdir")
    if mutating: require_confirm(req.confirm, "EXECUTE")
    result = run(["docker", "exec", "-w", req.workdir, name, *command], root)
    audit("project_container_exec", req.project_id, req.model_dump(), result); return result


@router.post("/http-check", dependencies=[Depends(auth)])
def project_http_check(req: ProjectHttpRequest) -> dict[str, Any]:
    load_manifest(req.project_id)
    if not req.url.startswith(("http://", "https://")): raise HTTPException(status_code=422, detail="invalid_url")
    method = req.method.upper()
    if method not in {"GET", "HEAD"}: raise HTTPException(status_code=422, detail="invalid_method")
    request = urllib.request.Request(req.url, method=method, headers={"User-Agent": "Vitrine-Ops/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = {"ok": True, "status": response.status, "final_url": response.geturl(), "headers": dict(response.headers.items())}
    except urllib.error.HTTPError as exc:
        result = {"ok": False, "status": exc.code, "final_url": exc.geturl(), "headers": dict(exc.headers.items())}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    audit("project_http_check", req.project_id, req.model_dump(), result); return result


@router.post("/port-check", dependencies=[Depends(auth)])
def project_port_check(req: ProjectPortRequest) -> dict[str, Any]:
    load_manifest(req.project_id)
    if not SAFE_HOST_RE.fullmatch(req.host) or not 1 <= req.port <= 65535: raise HTTPException(status_code=422, detail="invalid_host_or_port")
    try:
        with socket.create_connection((req.host, req.port), timeout=5): result = {"ok": True, "host": req.host, "port": req.port, "open": True}
    except OSError as exc:
        result = {"ok": True, "host": req.host, "port": req.port, "open": False, "error": str(exc)}
    audit("project_port_check", req.project_id, req.model_dump(), result); return result


@router.post("/compose-explicit", dependencies=[Depends(auth)])
def project_compose_explicit(req: ProjectComposeExplicitRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id); _, repository, _ = project_paths(manifest)
    compose = safe_project_file(repository, req.compose_file)
    if compose.suffix not in {".yml", ".yaml"} or not compose.is_file(): raise HTTPException(status_code=422, detail="invalid_compose_file")
    action = req.action.lower(); allowed = {"status": ["ps"], "config": ["config"], "up": ["up", "-d", "--build"], "restart": ["restart"], "logs": ["logs", "--tail", "200"]}
    if action not in allowed: raise HTTPException(status_code=422, detail="invalid_compose_action")
    if action in {"up", "restart"}: require_confirm(req.confirm, "EXECUTE")
    command = ["docker", "compose", "-f", str(compose)]
    if req.docker_project:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", req.docker_project): raise HTTPException(status_code=422, detail="invalid_docker_project")
        command += ["-p", req.docker_project]
    command += allowed[action]
    result = run(command, repository); audit("project_compose_explicit", req.project_id, req.model_dump(), result); return result


@router.post("/file-read-safe", dependencies=[Depends(auth)])
def project_file_read_safe(req: ProjectFileReadRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id); _, repository, _ = project_paths(manifest); path = safe_project_file(repository, req.path)
    if not path.is_file(): raise HTTPException(status_code=404, detail="file_not_found")
    max_bytes = max(1, min(req.max_bytes, 200000)); content = path.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    return {"ok": True, "project_id": req.project_id, "path": req.path, "content": content, "truncated": path.stat().st_size > max_bytes}


@router.post("/file-patch-text", dependencies=[Depends(auth)])
def project_file_patch_text(req: ProjectFilePatchRequest) -> dict[str, Any]:
    require_confirm(req.confirm, "WRITE"); manifest = load_manifest(req.project_id); _, repository, _ = project_paths(manifest); path = safe_project_file(repository, req.path)
    if not path.is_file(): raise HTTPException(status_code=404, detail="file_not_found")
    text = path.read_text(encoding="utf-8")
    count = text.count(req.old)
    if count != 1: raise HTTPException(status_code=409, detail={"expected_one_match": count})
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S"); backup = path.with_name(f"{path.name}.backup-connector-{stamp}"); shutil.copy2(path, backup)
    path.write_text(text.replace(req.old, req.new, 1), encoding="utf-8")
    result = {"ok": True, "project_id": req.project_id, "path": req.path, "backup": str(backup)}
    audit("project_file_patch_text", req.project_id, req.model_dump(), result); return result


@router.post("/manifest/repository-update", dependencies=[Depends(auth)])
def project_manifest_repository_update(req: ProjectManifestRepositoryUpdateRequest) -> dict[str, Any]:
    require_confirm(req.confirm, "UPDATE"); path = manifest_path(req.project_id)
    if not path.is_file(): raise HTTPException(status_code=404, detail="manifest_not_found")
    data = load_manifest(req.project_id)
    if not req.url.strip() or not req.branch.strip(): raise HTTPException(status_code=422, detail="repository_update_invalid")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S"); backup = path.with_name(f"{path.name}.backup-{stamp}"); shutil.copy2(path, backup)
    data["repository"]["url"] = req.url.strip(); data["repository"]["branch"] = req.branch.strip()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"ok": True, "project_id": req.project_id, "repository": data["repository"], "backup": str(backup)}
    audit("project_manifest_repository_update", req.project_id, req.model_dump(), result); return result
