from __future__ import annotations

from typing import Any

import main
import materialize_entrypoint  # noqa: F401 - registers v0.1.2-compatible tools
from foundation import capabilities, docker_ops, git_ops, policy, runtime_ops

main.VERSION = "0.2.2-gemini-probe"


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def policy_catalog() -> dict[str, Any]:
    result = {"ok": True, "policies": policy.catalog()}
    main._audit("policy.catalog", {}, {"ok": True, "count": len(result["policies"])})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_discover(project_id: str) -> dict[str, Any]:
    try:
        result = capabilities.discover(project_id)
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
    main._audit("project.discover", {"project_id": project_id}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_capability_check(project_id: str) -> dict[str, Any]:
    try:
        result = capabilities.capability_check(project_id)
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
    main._audit("project.capability_check", {"project_id": project_id}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def capability_gap_report(project_id: str) -> dict[str, Any]:
    try:
        result = capabilities.gap_report(project_id)
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        result = {"ok": False, "error": str(exc), "project_id": project_id}
    main._audit("capability.gap_report", {"project_id": project_id}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def git_head(project_id: str) -> dict[str, Any]:
    result = git_ops.head(project_id)
    main._audit("git.head", {"project_id": project_id}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def git_log(project_id: str, limit: int = 20) -> dict[str, Any]:
    result = git_ops.log(project_id, limit)
    main._audit("git.log", {"project_id": project_id, "limit": limit}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def git_diff(project_id: str, ref: str = "HEAD") -> dict[str, Any]:
    result = git_ops.diff(project_id, ref)
    main._audit("git.diff", {"project_id": project_id, "ref": ref}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def git_reconcile(project_id: str, branch: str = "", confirm: str = "") -> dict[str, Any]:
    return git_ops.reconcile(project_id, branch, confirm)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_runtime_config_status(project_id: str) -> dict[str, Any]:
    return runtime_ops.runtime_config_status(project_id)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_manifest_runtime_configure(project_id: str, runtime_allowed_keys: list[str], runtime_env_file: str = ".env.runtime", confirm: str = "") -> dict[str, Any]:
    return runtime_ops.manifest_runtime_configure(project_id, runtime_allowed_keys, runtime_env_file, confirm)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def project_runtime_secret_set(project_id: str, key: str, value: str, confirm: str = "") -> dict[str, Any]:
    return runtime_ops.runtime_secret_set(project_id, key, value, confirm)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_gemini_api_probe(project_id: str) -> dict[str, Any]:
    return runtime_ops.gemini_api_probe(project_id)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_status() -> dict[str, Any]:
    result = docker_ops.docker_status()
    main._audit("docker.status", {}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_image_inspect(image: str) -> dict[str, Any]:
    result = docker_ops.image_inspect(image)
    main._audit("docker.image_inspect", {"image": image}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_container_inspect(container: str) -> dict[str, Any]:
    result = docker_ops.docker_container_inspect(container)
    main._audit("docker.container_inspect", {"container": container}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_container_health(container: str) -> dict[str, Any]:
    result = docker_ops.docker_container_health(container)
    main._audit("docker.container_health", {"container": container}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_container_logs(container: str, tail: int = 200) -> dict[str, Any]:
    result = docker_ops.docker_container_logs(container, tail)
    main._audit("docker.container_logs", {"container": container, "tail": tail}, {"ok": result.get("ok")})
    return result


if __name__ == "__main__":
    main.mcp.run(transport="http", host="0.0.0.0", port=8000)
