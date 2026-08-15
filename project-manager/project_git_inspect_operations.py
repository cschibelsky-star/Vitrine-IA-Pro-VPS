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


def _commit_details(repository: Path, revision_range: str) -> list[dict[str, Any]]:
    shas = _run(repository, ["rev-list", "--max-count=20", revision_range]).splitlines()
    details: list[dict[str, Any]] = []
    for sha in shas:
        sha = sha.strip()
        if not sha:
            continue
        subject = _run(repository, ["show", "-s", "--format=%s", sha])
        parents = _run(repository, ["show", "-s", "--format=%P", sha]).split()
        changed = _run(repository, ["diff-tree", "--no-commit-id", "--name-status", "-r", sha])
        stat = _run(repository, ["show", "--format=", "--shortstat", sha])
        details.append({
            "sha": sha,
            "subject": subject,
            "parents": parents,
            "changed_files": changed.splitlines() if changed else [],
            "shortstat": stat,
        })
    return details


def _changed_paths(lines: str) -> set[str]:
    result: set[str] = set()
    for line in lines.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            result.add(parts[-1].strip())
    return result


def _blob_compare(repository: Path, head_ref: str, remote_ref: str, paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        local_blob = _run(repository, ["rev-parse", f"{head_ref}:{path}"])
        remote_blob = _run(repository, ["rev-parse", f"{remote_ref}:{path}"])
        rows.append({
            "path": path,
            "local_blob": local_blob,
            "remote_blob": remote_blob,
            "same": bool(local_blob and remote_blob and local_blob == remote_blob),
        })
    return rows


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
    local_changed = _run(repository, ["diff", "--name-status", f"{merge_base}..HEAD"]) if merge_base else ""
    remote_changed = _run(repository, ["diff", "--name-status", f"{merge_base}..{remote_ref}"]) if merge_base and remote else ""
    working_tree = _run(repository, ["status", "--short"])
    working_diff_stat = _run(repository, ["diff", "--stat"])
    working_diff = _run(repository, ["diff", "--no-ext-diff", "--unified=3"])
    if len(working_diff) > 50000:
        working_diff = working_diff[:50000] + "\n[TRUNCATED]"

    overlap = sorted(_changed_paths(local_changed) & _changed_paths(remote_changed))

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
        "local_only_details": _commit_details(repository, f"{remote_ref}..HEAD") if remote else [],
        "remote_only_details": _commit_details(repository, f"HEAD..{remote_ref}") if remote else [],
        "local_changed_from_merge_base": local_changed.splitlines() if local_changed else [],
        "remote_changed_from_merge_base": remote_changed.splitlines() if remote_changed else [],
        "overlap_blob_comparison": _blob_compare(repository, "HEAD", remote_ref, overlap) if remote else [],
        "working_tree": working_tree.splitlines() if working_tree else [],
        "working_diff_stat": working_diff_stat.splitlines() if working_diff_stat else [],
        "working_diff": working_diff,
    }
