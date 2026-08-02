from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/projects")

MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("PROJECT_MANAGER_TIMEOUT", "1200"))


class ProjectRequest(BaseModel):
    project_id: str


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def load_manifest(project_id: str) -> dict[str, Any]:
    if not project_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in project_id):
        raise HTTPException(status_code=422, detail="invalid_project_id")

    path = (MANIFEST_ROOT / f"{project_id}.json").resolve()
    if MANIFEST_ROOT not in path.parents:
        raise HTTPException(status_code=403, detail="manifest_path_blocked")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="manifest_not_found")

    data = json.loads(path.read_text(encoding="utf-8"))
    required = ["id", "workspace_root", "repository", "shared_directories"]
    missing = [key for key in required if key not in data]
    if missing:
        raise HTTPException(status_code=422, detail={"missing_manifest_fields": missing})
    if data["id"] != project_id:
        raise HTTPException(status_code=422, detail="manifest_id_mismatch")
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


def workspace_paths(manifest: dict[str, Any]) -> list[Path]:
    root = Path(manifest["workspace_root"]).resolve()
    paths = [
        root,
        root / manifest["repository"].get("directory", "repository"),
        root / manifest.get("release", {}).get("directory", "releases"),
        root / "scripts",
        root / "snapshots",
        root / "shared",
    ]
    paths.extend(root / "shared" / item for item in manifest["shared_directories"])
    return paths


@router.get("/{project_id}/manifest", dependencies=[Depends(auth)])
def project_manifest(project_id: str) -> dict[str, Any]:
    return {"ok": True, "manifest": load_manifest(project_id)}


@router.post("/workspace", dependencies=[Depends(auth)])
def project_workspace(req: ProjectRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id)
    paths = workspace_paths(manifest)
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "project_id": req.project_id, "paths": [str(path) for path in paths]}


@router.post("/clone", dependencies=[Depends(auth)])
def project_clone(req: ProjectRequest) -> dict[str, Any]:
    manifest = load_manifest(req.project_id)
    root = Path(manifest["workspace_root"]).resolve()
    repository = manifest["repository"]
    target = root / repository.get("directory", "repository")
    branch = repository.get("branch", "main")
    url = repository["url"]

    root.mkdir(parents=True, exist_ok=True)

    if (target / ".git").is_dir():
        fetch = run(["git", "fetch", "--all", "--prune"], target)
        if not fetch["ok"]:
            return {"ok": False, "stage": "fetch", "result": fetch}
        checkout = run(["git", "checkout", branch], target)
        if not checkout["ok"]:
            return {"ok": False, "stage": "checkout", "result": checkout}
        pull = run(["git", "pull", "--ff-only", "origin", branch], target)
        return {
            "ok": pull["ok"],
            "operation": "updated",
            "project_id": req.project_id,
            "repository": str(target),
            "result": pull,
        }

    if target.exists() and any(target.iterdir()):
        return {
            "ok": False,
            "stage": "preflight",
            "error": "repository_directory_not_empty",
            "repository": str(target),
        }

    if target.exists():
        target.rmdir()

    clone = run(
        ["git", "clone", "--branch", branch, "--single-branch", url, str(target)],
        root,
    )
    return {
        "ok": clone["ok"],
        "operation": "cloned",
        "project_id": req.project_id,
        "repository": str(target),
        "result": clone,
    }


@router.get("/{project_id}/status", dependencies=[Depends(auth)])
def project_status(project_id: str) -> dict[str, Any]:
    manifest = load_manifest(project_id)
    root = Path(manifest["workspace_root"]).resolve()
    repository = root / manifest["repository"].get("directory", "repository")
    status = run(["git", "status", "--short", "--branch"], repository) if (repository / ".git").is_dir() else None
    return {
        "ok": True,
        "project_id": project_id,
        "workspace_exists": root.exists(),
        "repository_exists": repository.exists(),
        "repository_is_git": (repository / ".git").is_dir(),
        "git_status": status,
    }
