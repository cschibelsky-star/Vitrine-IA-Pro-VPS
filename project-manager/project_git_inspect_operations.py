from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

router = APIRouter(prefix="/projects")

MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("PROJECT_MANAGER_TIMEOUT", "1200"))
ALLOWED_WORKSPACE_ROOTS = tuple(
    Path(item.strip()).resolve()
    for item in os.getenv("PROJECT_WORKSPACE_ROOTS", "/srv/tvsumare,/srv/projects").split(",")
    if item.strip()
)


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


def _run(repository: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repository),
        text=True,
        capture_output=True,
        timeout=TIMEOUT,
        check=False,
        env={"PATH": os.getenv("PATH", ""), "LC_ALL": "C.UTF-8"},
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


@router.get("/{project_id}/git-inspect", dependencies=[Depends(auth)])
def project_git_inspect(project_id: str) -> dict[str, Any]:
    data = _manifest(project_id)
    root = Path(str(data["workspace_root"])).resolve()
    repository = (root / str(data.get("repository", {}).get("directory", "repository"))).resolve()
    if not _within(repository, root) or not (repository / ".git").is_dir():
        raise HTTPException(status_code=404, detail="repository_not_git")

    branch = _run(repository, ["branch", "--show-current"])
    head = _run(repository, ["rev-parse", "HEAD"])
    configured_branch = str(data.get("repository", {}).get("branch", branch or "main"))
    remote_ref = f"origin/{configured_branch}"
    remote = _run(repository, ["rev-parse", "--verify", remote_ref])
    merge_base = _run(repository, ["merge-base", "HEAD", remote_ref]) if remote else ""
    counts = _run(repository, ["rev-list", "--left-right", "--count", f"HEAD...{remote_ref}"]) if remote else ""
    ahead = behind = None
    if counts:
        parts = counts.replace("\t", " ").split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    local_only = _run(repository, ["log", "--oneline", "--decorate=no", f"{remote_ref}..HEAD", "-n", "20"]) if remote else ""
    remote_only = _run(repository, ["log", "--oneline", "--decorate=no", f"HEAD..{remote_ref}", "-n", "20"]) if remote else ""

    return {
        "ok": True,
        "project_id": project_id,
        "branch": branch,
        "configured_branch": configured_branch,
        "head": head,
        "remote_ref": remote_ref,
        "remote_head": remote,
        "merge_base": merge_base,
        "ahead": ahead,
        "behind": behind,
        "local_only_commits": local_only.splitlines() if local_only else [],
        "remote_only_commits": remote_only.splitlines() if remote_only else [],
    }
