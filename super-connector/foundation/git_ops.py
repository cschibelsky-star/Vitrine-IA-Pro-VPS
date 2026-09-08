from __future__ import annotations

from typing import Any

import main
from foundation.policy import authorize


def head(project_id: str) -> dict[str, Any]:
    project = main._load_project(project_id)
    repository = main._repository(project)
    branch = main._run(["git", "branch", "--show-current"], repository, timeout=30)
    sha = main._run(["git", "rev-parse", "HEAD"], repository, timeout=30)
    return {
        "ok": bool(branch.get("ok") and sha.get("ok")),
        "project_id": project_id,
        "branch": str(branch.get("stdout", "")).strip(),
        "head": str(sha.get("stdout", "")).strip(),
    }


def log(project_id: str, limit: int = 20) -> dict[str, Any]:
    project = main._load_project(project_id)
    repository = main._repository(project)
    safe_limit = max(1, min(int(limit), 100))
    result = main._run(
        ["git", "log", f"-{safe_limit}", "--date=iso-strict", "--pretty=format:%H%x09%ad%x09%s"],
        repository,
        timeout=60,
    )
    return {**result, "project_id": project_id, "limit": safe_limit}


def diff(project_id: str, ref: str = "HEAD") -> dict[str, Any]:
    project = main._load_project(project_id)
    repository = main._repository(project)
    target = str(ref or "HEAD").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
    if any(ch not in allowed for ch in target) or ".." in target.split("/"):
        return {"ok": False, "error": "invalid_git_ref"}
    result = main._run(["git", "diff", "--stat", target], repository, timeout=60)
    return {**result, "project_id": project_id, "ref": target}


def reconcile(project_id: str, branch: str = "", confirm: str = "") -> dict[str, Any]:
    auth = authorize("git_reconcile", confirm=confirm)
    if not auth.get("ok"):
        return auth
    comparison = main.git_compare(project_id, branch)
    if not comparison.get("ok"):
        return comparison
    if comparison.get("dirty"):
        return {
            "ok": False,
            "error": "dirty_tree_requires_preservation",
            "project_id": project_id,
            "comparison": comparison,
        }
    ahead = comparison.get("ahead")
    behind = comparison.get("behind")
    if ahead is None or behind is None:
        return {"ok": False, "error": "git_divergence_unknown", "comparison": comparison}
    if ahead > 0 and behind > 0:
        return {
            "ok": False,
            "error": "git_history_diverged",
            "project_id": project_id,
            "comparison": comparison,
        }
    if ahead > 0:
        return {
            "ok": False,
            "error": "local_commits_require_push_or_preservation",
            "project_id": project_id,
            "comparison": comparison,
        }
    if behind == 0:
        return {"ok": True, "status": "already_up_to_date", "comparison": comparison}
    project = main._load_project(project_id)
    repository = main._repository(project)
    target = main._safe_branch(branch or str(project.get("repository", {}).get("branch", "main")))
    result = main._run(["git", "merge", "--ff-only", f"origin/{target}"], repository, timeout=300)
    response = {**result, "project_id": project_id, "branch": target, "strategy": "fast_forward_only"}
    main._audit(
        "git.reconcile",
        {"project_id": project_id, "branch": target, "strategy": "fast_forward_only"},
        {"ok": response.get("ok"), "exit_code": response.get("exit_code")},
    )
    return response
