from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import main as core

mcp = core.mcp


def _require_execute(confirm: str) -> None:
    if confirm != "EXECUTAR":
        raise PermissionError("confirmation_required")


def _safe_workspace(workspace_root: str) -> Path:
    workspace = Path(str(workspace_root or "")).resolve()
    if not any(core._within(workspace, root) for root in core.ALLOWED_WORKSPACE_ROOTS):
        raise PermissionError("workspace_root_blocked")
    return workspace


def _validated_repository_url(repository_url: str) -> str:
    value = str(repository_url or "").strip()
    if value.startswith("git@github.com:") and value.endswith(".git"):
        return value
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.hostname == "github.com" and parsed.path.count("/") >= 2:
        return value if value.endswith(".git") else value + ".git"
    raise ValueError("repository_url_not_allowed")


def _clone_url(repository_url: str) -> str:
    value = _validated_repository_url(repository_url)
    if value.startswith("https://github.com/"):
        path = value[len("https://github.com/"):]
        return f"git@github.com:{path}"
    return value


@mcp.tool()
def project_manifest_create(
    project_id: str,
    name: str,
    workspace_root: str,
    repository_url: str,
    branch: str = "main",
    repository_directory: str = "repository",
    shared_directories: list[str] | None = None,
    compose_file: str = "",
    docker_project: str = "",
    release_directory: str = "releases",
    confirm: str = "",
) -> dict:
    _require_execute(confirm)
    pid = core._safe_project_id(project_id)
    workspace = _safe_workspace(workspace_root)
    repo_url = _validated_repository_url(repository_url)
    repo_dir = str(repository_directory or "repository").strip()
    if not repo_dir or Path(repo_dir).is_absolute() or ".." in Path(repo_dir).parts:
        raise ValueError("invalid_repository_directory")
    release_dir = str(release_directory or "releases").strip()
    if not release_dir or Path(release_dir).is_absolute() or ".." in Path(release_dir).parts:
        raise ValueError("invalid_release_directory")
    branch_value = str(branch or "main").strip()
    if not branch_value or any(ch.isspace() for ch in branch_value):
        raise ValueError("invalid_branch")

    target = (core.MANIFEST_ROOT / f"{pid}.json").resolve()
    if core.MANIFEST_ROOT not in target.parents:
        raise PermissionError("manifest_path_blocked")
    if target.exists():
        return {"ok": False, "error": "manifest_already_exists", "project_id": pid}

    shared = shared_directories or ["data", "uploads", "logs", "cache", "secrets"]
    for item in shared:
        p = Path(str(item))
        if p.is_absolute() or ".." in p.parts or not str(item).strip():
            raise ValueError("invalid_shared_directory")

    manifest = {
        "id": pid,
        "name": str(name or pid).strip(),
        "workspace_root": str(workspace),
        "repository": {
            "url": repo_url,
            "branch": branch_value,
            "directory": repo_dir,
        },
        "shared_directories": shared,
        "docker": {
            "compose_file": str(compose_file or ""),
            "project_name": str(docker_project or pid),
            "service": None,
        },
        "domains": {"homologation": [], "production": []},
        "deployment": {},
        "backup_root": f"/srv/backups/{pid}",
        "release": {"directory": release_dir, "exclude": [".git", ".env", "shared", "vendor", "node_modules"]},
    }
    core.MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    result = {"ok": True, "project_id": pid, "manifest_path": str(target), "manifest": manifest}
    core._audit("project_manifest_create", {"project_id": pid, "workspace_root": str(workspace), "repository_url": repo_url}, result)
    return result


@mcp.tool()
def project_workspace(project_id: str, confirm: str = "") -> dict:
    _require_execute(confirm)
    manifest, workspace, repository = core._project_paths(project_id)
    created = []
    for path in [workspace, workspace / "shared", workspace / "releases", workspace / "scripts", workspace / "snapshots"]:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path))
    for item in manifest.get("shared_directories", []):
        path = workspace / "shared" / str(item)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path))
    result = {"ok": True, "project_id": project_id, "workspace_root": str(workspace), "repository_root": str(repository), "created": created}
    core._audit("project_workspace", {"project_id": project_id}, result)
    return result


@mcp.tool()
def project_clone(project_id: str, confirm: str = "") -> dict:
    _require_execute(confirm)
    manifest, workspace, repository = core._project_paths(project_id)
    if (repository / ".git").is_dir():
        return {"ok": True, "project_id": project_id, "status": "already_cloned", "repository_root": str(repository)}
    if repository.exists() and any(repository.iterdir()):
        return {"ok": False, "error": "repository_directory_not_empty", "repository_root": str(repository)}
    repository.parent.mkdir(parents=True, exist_ok=True)
    repo = manifest.get("repository", {})
    url = _clone_url(str(repo.get("url", "")))
    branch = str(repo.get("branch", "main"))
    result = core._run(["git", "clone", "--branch", branch, "--single-branch", url, str(repository)], workspace)
    result.update({"project_id": project_id, "repository_root": str(repository), "branch": branch})
    core._audit("project_clone", {"project_id": project_id, "branch": branch}, result)
    return result


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
