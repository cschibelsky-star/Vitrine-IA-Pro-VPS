from __future__ import annotations

import json
import os
import subprocess
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
    for item in os.getenv(
        "PROJECT_WORKSPACE_ROOTS",
        "/srv/tvsumare,/srv/projects",
    ).split(",")
    if item.strip()
)


class ProjectRequest(BaseModel):
    project_id: str


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
