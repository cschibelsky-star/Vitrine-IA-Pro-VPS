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

router = APIRouter(prefix="/projects")

MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("PROJECT_MANAGER_TIMEOUT", "1200"))
ALLOWED_WORKSPACE_ROOTS = tuple(
    Path(item.strip()).resolve()
    for item in os.getenv("PROJECT_WORKSPACE_ROOTS", "/srv/tvsumare,/srv/projects").split(",")
    if item.strip()
)


class RecoveryBranchRequest(BaseModel):
    project_id: str
    recovery_branch: str
    confirm: str = ""


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _manifest(project_id: str) -> dict[str, Any]:
    if not project_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in project_id):
        raise HTTPException(status_code=422, detail="invalid_project_id")
    path = (MANIFEST_ROOT / f"{project_id}.json").resolve()
    if MANIFEST_ROOT not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="manifest_not_found")
    data = json.loads(path.read_text(encoding="utf-8"))
    root = Path(str(data["workspace_root"])).resolve()
    if not any(_within(root, allowed) for allowed in ALLOWED_WORKSPACE_ROOTS):
        raise HTTPException(status_code=403, detail="workspace_root_blocked")
    return data


def _run(repository: Path, args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repository),
        text=True,
        capture_output=True,
        timeout=TIMEOUT,
        check=False,
        env={**os.environ, "LC_ALL": "C.UTF-8"},
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
    }


@router.post("/git-recovery-branch", dependencies=[Depends(auth)])
def project_git_recovery_branch(req: RecoveryBranchRequest) -> dict[str, Any]:
    if req.confirm != "EXECUTAR":
        raise HTTPException(status_code=422, detail="confirmation_required")
    branch = str(req.recovery_branch or "").strip()
    if not re.fullmatch(r"recovery/[a-z0-9][a-z0-9._/-]{2,100}", branch):
        raise HTTPException(status_code=422, detail="invalid_recovery_branch")
    if ".." in branch or branch.endswith("/") or branch.startswith("/"):
        raise HTTPException(status_code=422, detail="invalid_recovery_branch")

    data = _manifest(req.project_id)
    root = Path(str(data["workspace_root"])).resolve()
    repository = (root / str(data.get("repository", {}).get("directory", "repository"))).resolve()
    if not _within(repository, root) or not (repository / ".git").is_dir():
        raise HTTPException(status_code=404, detail="repository_not_git")

    head = _run(repository, ["rev-parse", "HEAD"])
    if not head["ok"]:
        return {"ok": False, "stage": "head", "result": head}
    head_sha = head["stdout"].strip()

    remote_check = _run(repository, ["ls-remote", "--heads", "origin", f"refs/heads/{branch}"])
    if not remote_check["ok"]:
        return {"ok": False, "stage": "remote_check", "result": remote_check}
    if remote_check["stdout"].strip():
        return {
            "ok": False,
            "stage": "preflight",
            "error": "recovery_branch_already_exists",
            "recovery_branch": branch,
        }

    push = _run(repository, ["push", "origin", f"HEAD:refs/heads/{branch}"])
    return {
        "ok": push["ok"],
        "project_id": req.project_id,
        "recovery_branch": branch,
        "head": head_sha,
        "pushed_at": datetime.now(timezone.utc).isoformat(),
        "result": push,
    }
