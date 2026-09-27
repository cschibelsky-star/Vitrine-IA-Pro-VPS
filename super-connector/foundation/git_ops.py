from __future__ import annotations

import secrets
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


def checkout(project_id: str, branch: str, confirm: str = "") -> dict[str, Any]:
    auth = authorize("git_checkout", confirm=confirm)
    if not auth.get("ok"):
        return auth

    project = main._load_project(project_id)
    repository = main._repository(project)
    target = main._safe_branch(branch)

    status = main._run(["git", "status", "--porcelain"], repository, timeout=30)
    if not status.get("ok"):
        return {"ok": False, "error": "git_status_failed", "detail": status}
    if str(status.get("stdout", "")).strip():
        return {"ok": False, "error": "dirty_tree_checkout_blocked", "project_id": project_id}

    current_result = main._run(["git", "branch", "--show-current"], repository, timeout=30)
    if not current_result.get("ok"):
        return {"ok": False, "error": "current_branch_check_failed", "detail": current_result}
    current = str(current_result.get("stdout", "")).strip()
    if not current:
        return {"ok": False, "error": "detached_head_not_supported", "project_id": project_id}

    fetch = main._run(["git", "fetch", "--prune", "origin"], repository, timeout=180)
    if not fetch.get("ok"):
        return {"ok": False, "error": "git_fetch_failed", "detail": fetch}

    target_ref = f"refs/remotes/origin/{target}"
    target_check = main._run(["git", "rev-parse", "--verify", target_ref], repository, timeout=30)
    if not target_check.get("ok"):
        return {"ok": False, "error": "target_remote_branch_not_found", "project_id": project_id, "target_branch": target}

    source_sha_result = main._run(["git", "rev-parse", "HEAD"], repository, timeout=30)
    if not source_sha_result.get("ok"):
        return {"ok": False, "error": "source_head_unavailable", "detail": source_sha_result}
    source_sha = str(source_sha_result.get("stdout", "")).strip()

    ancestor = main._run(["git", "merge-base", "--is-ancestor", source_sha, f"origin/{target}"], repository, timeout=30)
    if ancestor.get("exit_code") != 0:
        return {
            "ok": False,
            "error": "target_does_not_contain_current_head",
            "project_id": project_id,
            "current_branch": current,
            "target_branch": target,
            "current_head": source_sha,
        }

    result = main._run(["git", "checkout", "-B", target, f"origin/{target}"], repository, timeout=120)
    if not result.get("ok"):
        return {"ok": False, "error": "git_checkout_failed", "detail": result}

    head_result = main._run(["git", "rev-parse", "HEAD"], repository, timeout=30)
    response = {
        **result,
        "project_id": project_id,
        "previous_branch": current,
        "target_branch": target,
        "head": str(head_result.get("stdout", "")).strip() if head_result.get("ok") else "",
        "preserved": True,
    }
    main._audit(
        "git.checkout",
        {"project_id": project_id, "previous_branch": current, "target_branch": target},
        {"ok": response.get("ok"), "head": response.get("head")},
    )
    return response


def reconcile(project_id: str, branch: str = "", confirm: str = "") -> dict[str, Any]:
    auth = authorize("git_reconcile", confirm=confirm)
    if not auth.get("ok"):
        return auth

    project = main._load_project(project_id)
    repository = main._repository(project)
    target = main._safe_branch(branch or str(project.get("repository", {}).get("branch", "main")))

    current_result = main._run(["git", "branch", "--show-current"], repository, timeout=30)
    if not current_result.get("ok"):
        return {"ok": False, "error": "current_branch_check_failed", "detail": current_result}

    current = str(current_result.get("stdout", "")).strip()
    if not current:
        return {"ok": False, "error": "detached_head_not_supported", "project_id": project_id}

    status = main._run(["git", "status", "--porcelain"], repository, timeout=30)
    if not status.get("ok"):
        return {"ok": False, "error": "git_status_failed", "detail": status}
    if str(status.get("stdout", "")).strip():
        return {
            "ok": False,
            "error": "dirty_tree_requires_preservation",
            "project_id": project_id,
            "current_branch": current,
            "target_branch": target,
        }

    fetch = main._run(["git", "fetch", "--prune", "origin"], repository, timeout=180)
    if not fetch.get("ok"):
        return {"ok": False, "error": "git_fetch_failed", "detail": fetch}

    source_sha_result = main._run(["git", "rev-parse", "HEAD"], repository, timeout=30)
    if not source_sha_result.get("ok"):
        return {"ok": False, "error": "source_head_unavailable", "detail": source_sha_result}
    source_sha = str(source_sha_result.get("stdout", "")).strip()

    target_ref = f"refs/remotes/origin/{target}"
    target_check = main._run(["git", "rev-parse", "--verify", target_ref], repository, timeout=30)
    if not target_check.get("ok"):
        return {
            "ok": False,
            "error": "target_remote_branch_not_found",
            "project_id": project_id,
            "target_branch": target,
        }

    if current == target:
        counts = main._run(
            ["git", "rev-list", "--left-right", "--count", f"HEAD...origin/{target}"],
            repository,
            timeout=30,
        )
        if not counts.get("ok"):
            return {"ok": False, "error": "git_divergence_unknown", "detail": counts}
        try:
            ahead_s, behind_s = str(counts.get("stdout", "")).strip().split()
            ahead, behind = int(ahead_s), int(behind_s)
        except (ValueError, TypeError):
            return {"ok": False, "error": "git_divergence_parse_failed", "detail": counts}

        if ahead > 0 and behind > 0:
            return {
                "ok": False,
                "error": "same_branch_history_diverged",
                "project_id": project_id,
                "comparison": {"ahead": ahead, "behind": behind},
            }
        if behind > 0:
            result = main._run(["git", "merge", "--ff-only", f"origin/{target}"], repository, timeout=300)
            strategy = "fast_forward_local"
        elif ahead > 0:
            result = main._run(["git", "push", "origin", f"HEAD:refs/heads/{target}"], repository, timeout=300)
            strategy = "fast_forward_remote"
        else:
            result = {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}
            strategy = "already_up_to_date"

        response = {
            **result,
            "project_id": project_id,
            "source_branch": current,
            "target_branch": target,
            "strategy": strategy,
            "source_preserved": True,
            "runtime_worktree_untouched": strategy != "fast_forward_local",
        }
        main._audit(
            "git.reconcile",
            {"project_id": project_id, "source_branch": current, "target_branch": target, "strategy": strategy},
            {"ok": response.get("ok"), "exit_code": response.get("exit_code")},
        )
        return response

    preserve = main._run(
        ["git", "push", "origin", f"{source_sha}:refs/heads/{current}"],
        repository,
        timeout=300,
    )
    if not preserve.get("ok"):
        return {
            "ok": False,
            "error": "source_branch_preservation_failed",
            "project_id": project_id,
            "current_branch": current,
            "target_branch": target,
            "detail": preserve,
        }

    ancestor = main._run(
        ["git", "merge-base", "--is-ancestor", f"origin/{target}", source_sha],
        repository,
        timeout=30,
    )
    if ancestor.get("exit_code") == 0:
        result = main._run(
            ["git", "push", "origin", f"{source_sha}:refs/heads/{target}"],
            repository,
            timeout=300,
        )
        response = {
            **result,
            "project_id": project_id,
            "source_branch": current,
            "target_branch": target,
            "strategy": "fast_forward_target",
            "source_preserved": True,
            "runtime_worktree_untouched": True,
        }
        main._audit(
            "git.reconcile",
            {"project_id": project_id, "source_branch": current, "target_branch": target, "strategy": "fast_forward_target"},
            {"ok": response.get("ok"), "exit_code": response.get("exit_code")},
        )
        return response

    worktree_root = repository.parent / ".git-reconcile-worktrees"
    worktree_root.mkdir(parents=True, exist_ok=True)
    safe_target = target.replace("/", "-")
    worktree = worktree_root / f"{project_id}-{safe_target}-{secrets.token_hex(4)}"

    added = main._run(
        ["git", "worktree", "add", "--detach", str(worktree), f"origin/{target}"],
        repository,
        timeout=120,
    )
    if not added.get("ok"):
        return {"ok": False, "error": "temporary_worktree_create_failed", "detail": added}

    try:
        merge = main._run(
            ["git", "merge", "--no-ff", "--no-edit", source_sha],
            worktree,
            timeout=300,
        )
        if not merge.get("ok"):
            conflicts = main._run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                worktree,
                timeout=30,
            )
            main._run(["git", "merge", "--abort"], worktree, timeout=30)
            response = {
                "ok": False,
                "error": "git_merge_conflict",
                "project_id": project_id,
                "source_branch": current,
                "target_branch": target,
                "conflicts": [
                    item for item in str(conflicts.get("stdout", "")).splitlines() if item.strip()
                ],
                "source_preserved": True,
                "runtime_worktree_untouched": True,
            }
            main._audit(
                "git.reconcile",
                {"project_id": project_id, "source_branch": current, "target_branch": target, "strategy": "merge_no_ff"},
                {"ok": False, "error": "git_merge_conflict", "conflict_count": len(response["conflicts"])},
            )
            return response

        merged_sha_result = main._run(["git", "rev-parse", "HEAD"], worktree, timeout=30)
        if not merged_sha_result.get("ok"):
            return {"ok": False, "error": "merged_head_unavailable", "detail": merged_sha_result}
        merged_sha = str(merged_sha_result.get("stdout", "")).strip()

        pushed = main._run(
            ["git", "push", "origin", f"{merged_sha}:refs/heads/{target}"],
            worktree,
            timeout=300,
        )
        response = {
            **pushed,
            "project_id": project_id,
            "source_branch": current,
            "target_branch": target,
            "merged_head": merged_sha if pushed.get("ok") else "",
            "strategy": "merge_no_ff",
            "source_preserved": True,
            "runtime_worktree_untouched": True,
        }
        main._audit(
            "git.reconcile",
            {"project_id": project_id, "source_branch": current, "target_branch": target, "strategy": "merge_no_ff"},
            {"ok": response.get("ok"), "exit_code": response.get("exit_code"), "merged_head": response.get("merged_head", "")},
        )
        return response
    finally:
        main._run(["git", "worktree", "remove", "--force", str(worktree)], repository, timeout=120)
        main._run(["git", "worktree", "prune"], repository, timeout=30)
