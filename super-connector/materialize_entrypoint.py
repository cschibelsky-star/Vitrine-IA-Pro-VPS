from __future__ import annotations

from pathlib import Path
from typing import Any

import main


def _workspace(project: dict[str, Any]) -> Path:
    workspace = Path(project["workspace"]["root"]).resolve()
    if not any(workspace == root or root in workspace.parents for root in main.WORKSPACE_ROOTS):
        raise PermissionError("workspace_root_blocked")
    return workspace


def _safe_repository_url(value: str) -> str:
    url = str(value or "").strip()
    if not url:
        raise ValueError("repository_url_required")
    if url.startswith("https://github.com/") or url.startswith("git@github.com:"):
        return url
    raise ValueError("repository_url_not_allowed")


def _safe_compose_service(value: str) -> str:
    service = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    if not service or any(ch not in allowed for ch in service):
        raise ValueError("invalid_compose_service")
    return service


def _safe_compose_project_name(value: str) -> str:
    project_name = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    if not project_name or any(ch not in allowed for ch in project_name):
        raise ValueError("invalid_compose_project_name")
    return project_name


def _compose_file(project: dict[str, Any], repository: Path) -> Path:
    configured = str(project.get("docker", {}).get("compose_file", "") or "").strip().replace("\\", "/")
    if not configured:
        raise ValueError("compose_file_not_configured")
    if configured.startswith("/") or ".." in configured.split("/"):
        raise ValueError("invalid_compose_file")
    compose_file = (repository / configured).resolve()
    if repository != compose_file and repository not in compose_file.parents:
        raise PermissionError("compose_file_outside_repository")
    if not compose_file.is_file():
        raise FileNotFoundError("compose_file_not_found")
    return compose_file


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_materialize(project_id: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}

    try:
        project = main._load_project(project_id)
        workspace = _workspace(project)
        repository = main._repository(project)
        branch = main._safe_branch(str(project.get("repository", {}).get("branch", "main") or "main"))
        repository_url = _safe_repository_url(str(project.get("repository", {}).get("url", "")))
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
        main._audit("project.materialize", {"project_id": project_id}, result)
        return result

    if repository.exists():
        result = {
            "ok": False,
            "error": "repository_target_already_exists",
            "project_id": project_id,
            "repository": str(repository),
        }
        main._audit("project.materialize", {"project_id": project_id}, result)
        return result

    if workspace.exists():
        try:
            existing = sorted(item.name for item in workspace.iterdir())
        except OSError as exc:
            result = {"ok": False, "error": type(exc).__name__, "project_id": project_id}
            main._audit("project.materialize", {"project_id": project_id}, result)
            return result
        if existing:
            result = {
                "ok": False,
                "error": "workspace_not_empty",
                "project_id": project_id,
                "workspace": str(workspace),
                "entries": existing[:50],
            }
            main._audit("project.materialize", {"project_id": project_id}, result)
            return result
    else:
        try:
            workspace.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            result = {"ok": False, "error": type(exc).__name__, "project_id": project_id}
            main._audit("project.materialize", {"project_id": project_id}, result)
            return result

    result = main._run(
        [
            "git",
            "clone",
            "--branch",
            branch,
            "--single-branch",
            "--",
            repository_url,
            str(repository),
        ],
        workspace,
        timeout=900,
    )

    materialized = bool(result.get("ok") and (repository / ".git").is_dir())
    response = {
        "ok": materialized,
        "project_id": project_id,
        "workspace": str(workspace),
        "repository": str(repository),
        "branch": branch,
        "repository_url": repository_url,
        "exit_code": result.get("exit_code"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }
    if not materialized and result.get("ok"):
        response["error"] = "clone_completed_but_git_directory_missing"

    main._audit(
        "project.materialize",
        {"project_id": project_id, "branch": branch, "repository": str(repository)},
        {"ok": response["ok"], "exit_code": response.get("exit_code")},
    )
    return response


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_compose_service_execute(
    project_id: str,
    service: str,
    operation: str,
    confirm: str = "",
) -> dict[str, Any]:
    op = str(operation or "").strip().lower()
    allowed_operations = {"build", "up", "status", "logs"}
    if op not in allowed_operations:
        return {
            "ok": False,
            "error": "compose_operation_not_allowed",
            "allowed_operations": sorted(allowed_operations),
        }
    if op in {"build", "up"} and confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}

    try:
        project = main._load_project(project_id)
        repository = main._repository(project)
        compose_file = _compose_file(project, repository)
        service_name = _safe_compose_service(service)
        project_name = _safe_compose_project_name(
            str(project.get("docker", {}).get("project_name", project_id) or project_id)
        )
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
        main._audit(
            "project.compose_service_execute",
            {"project_id": project_id, "service": service, "operation": op},
            result,
        )
        return result

    base = [
        "docker",
        "compose",
        "-p",
        project_name,
        "-f",
        str(compose_file),
    ]
    if op == "build":
        command = [*base, "build", service_name]
        timeout = 1800
    elif op == "up":
        command = [*base, "up", "-d", service_name]
        timeout = 600
    elif op == "status":
        command = [*base, "ps", service_name]
        timeout = 60
    else:
        command = [*base, "logs", "--tail", "200", service_name]
        timeout = 60

    result = main._run(command, repository, timeout=timeout)
    response = {
        **result,
        "project_id": project_id,
        "service": service_name,
        "operation": op,
        "compose_file": str(compose_file),
        "docker_project": project_name,
    }
    main._audit(
        "project.compose_service_execute",
        {"project_id": project_id, "service": service_name, "operation": op},
        {"ok": response.get("ok"), "exit_code": response.get("exit_code")},
    )
    return response


if __name__ == "__main__":
    main.mcp.run(transport="http", host="0.0.0.0", port=8000)
