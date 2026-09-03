from __future__ import annotations

from pathlib import Path

ROOT = Path('/runtime')


def patch_operations() -> None:
    path = ROOT / 'project_manager_operations.py'
    text = path.read_text(encoding='utf-8')
    if 'class WorkspaceActionRequest(BaseModel):' not in text:
        anchor = 'class ProjectGitPushRequest(BaseModel):\n    project_id: str\n    confirm: str = ""\n'
        block = anchor + '\n\nclass WorkspaceActionRequest(BaseModel):\n    project_id: str\n    action: str\n    name: str = ""\n    branch: str = ""\n    include_untracked: bool = True\n    confirm: str = ""\n'
        if anchor not in text:
            raise RuntimeError('workspace request anchor not found')
        text = text.replace(anchor, block, 1)

    if 'def project_workspace_action(req: WorkspaceActionRequest)' not in text:
        marker = '\n\n@router.post("/git/stage", dependencies=[Depends(auth)])\n'
        block = '''\n\ndef require_workspace_confirm(value: str) -> None:\n    if value != "EXECUTAR":\n        raise HTTPException(status_code=409, detail="confirmation_required")\n\n\ndef workspace_status_payload(project_id: str, repository: Path) -> dict[str, Any]:\n    if not (repository / ".git").exists():\n        return {"ok": False, "project_id": project_id, "error": "repository_not_git"}\n    branch = run(["git", "branch", "--show-current"], repository)\n    head = run(["git", "rev-parse", "HEAD"], repository)\n    short = run(["git", "status", "--short", "--branch"], repository)\n    stash = run(["git", "stash", "list"], repository)\n    return {\n        "ok": branch["ok"] and head["ok"] and short["ok"],\n        "project_id": project_id,\n        "repository": str(repository),\n        "branch": branch["stdout"].strip(),\n        "head": head["stdout"].strip(),\n        "git_status": short,\n        "stash_list": stash,\n    }\n\n\n@router.post("/workspace/action", dependencies=[Depends(auth)])\ndef project_workspace_action(req: WorkspaceActionRequest) -> dict[str, Any]:\n    manifest = load_manifest(req.project_id)\n    _, repository, _ = project_paths(manifest)\n    action = req.action.strip().lower()\n\n    if action == "status":\n        result = workspace_status_payload(req.project_id, repository)\n        audit("workspace_status", req.project_id, req.model_dump(), result)\n        return result\n\n    if not (repository / ".git").exists():\n        raise HTTPException(status_code=422, detail="repository_not_git")\n\n    require_workspace_confirm(req.confirm)\n\n    if action == "stash":\n        message = req.name.strip() or f"centro-operacional-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"\n        command = ["git", "stash", "push", "-m", message]\n        if req.include_untracked:\n            command.insert(3, "--include-untracked")\n        result = run(command, repository)\n        status = workspace_status_payload(req.project_id, repository)\n        response = {"ok": result["ok"], "result": result, "status": status}\n        audit("workspace_stash", req.project_id, {"name": message, "include_untracked": req.include_untracked}, response)\n        return response\n\n    raise HTTPException(status_code=403, detail="workspace_action_not_allowed")\n'''
        if marker not in text:
            raise RuntimeError('workspace endpoint marker not found')
        text = text.replace(marker, block + marker, 1)

    path.write_text(text, encoding='utf-8')


def patch_main() -> None:
    path = ROOT / 'main.py'
    text = path.read_text(encoding='utf-8')
    import_anchor = '    project_git_push_explicit as _project_git_push_explicit,\n'
    import_line = '    project_workspace_action as _project_workspace_action,\n'
    if import_line.strip() not in text:
        if import_anchor not in text:
            raise RuntimeError('main import anchor not found')
        text = text.replace(import_anchor, import_anchor + import_line, 1)

    if 'def project_workspace_action(' not in text:
        marker = '\nif __name__ == "__main__":\n'
        block = '''\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_workspace_action(\n    project_id: str,\n    action: str,\n    name: str = "",\n    branch: str = "",\n    include_untracked: bool = True,\n    confirm: str = "",\n) -> dict[str, Any]:\n    return _project_workspace_action(project_id, action, name, branch, include_untracked, confirm)\n'''
        if marker not in text:
            raise RuntimeError('main tool marker not found')
        text = text.replace(marker, block + marker, 1)

    path.write_text(text, encoding='utf-8')


def main() -> None:
    patch_operations()
    patch_main()
    print('PROJECT_WORKSPACE_ACTION_RUNTIME_OK')


if __name__ == '__main__':
    main()
