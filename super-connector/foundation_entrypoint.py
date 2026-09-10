from __future__ import annotations

from typing import Any

import main
import materialize_entrypoint  # noqa: F401 - registers v0.1.2-compatible tools
from foundation import capabilities, docker_ops, files_ops, git_ops, laravel_ops, php_ops, policy, recovery_ops, runtime_ops

main.VERSION = "0.3.2-files-php"


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
def project_file_read_safe(project_id: str, path: str, max_bytes: int = 100000) -> dict[str, Any]:
    return files_ops.read_safe(project_id, path, max_bytes)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_read_file(project_id: str, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:
    return files_ops.read_lines(project_id, path, start_line, end_line)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_php_lint(project_id: str, path: str) -> dict[str, Any]:
    return php_ops.php_lint(project_id, path)


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
def laravel_test_v2(project_id: str) -> dict[str, Any]:
    return laravel_ops.laravel_test_v2(project_id)


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def project_video_producer_validate(project_id: str) -> dict[str, Any]:
    return php_ops.video_producer_validate(project_id)


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def project_video_producer_generate(project_id: str, request_id: str, title: str, prompt: str, aspect_ratio: str = "9:16", duration: int = 8, resolution: str = "720p", confirm: str = "") -> dict[str, Any]:
    return php_ops.video_producer_generate(project_id, request_id, title, prompt, aspect_ratio, duration, resolution, confirm)


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
    result = docker_ops.container_inspect(container)
    main._audit("docker.container_inspect", {"container": container}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_container_health(container: str) -> dict[str, Any]:
    result = docker_ops.container_health(container)
    main._audit("docker.container_health", {"container": container}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def docker_container_logs(container: str, tail: int = 200) -> dict[str, Any]:
    result = docker_ops.container_logs(container, tail)
    main._audit("docker.container_logs", {"container": container, "tail": tail}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def connector_endpoint_check(hostname: str, path: str = "/mcp") -> dict[str, Any]:
    result = recovery_ops.connector_endpoint_check(hostname, path)
    main._audit("recovery.connector_endpoint_check", {"hostname": hostname, "path": path}, {"ok": result.get("ok"), "status_code": result.get("status_code")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def proxy_route_inspect(hostname: str) -> dict[str, Any]:
    result = recovery_ops.proxy_route_inspect(hostname)
    main._audit("recovery.proxy_route_inspect", {"hostname": hostname}, {"ok": result.get("ok"), "match_count": result.get("match_count")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def mcp_publication_check(hostname: str, container: str = "") -> dict[str, Any]:
    result = recovery_ops.mcp_publication_check(hostname, container)
    main._audit("recovery.mcp_publication_check", {"hostname": hostname, "container": container}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def hml_route_inspect(route_id: str) -> dict[str, Any]:
    result = recovery_ops.hml_route_inspect(route_id)
    main._audit("routing.hml_route_inspect", {"route_id": route_id}, {"ok": result.get("ok")})
    return result


@main.mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def hml_route_activate(route_id: str, confirm: str = "") -> dict[str, Any]:
    result = recovery_ops.hml_route_activate(route_id, confirm)
    main._audit("routing.hml_route_activate", {"route_id": route_id}, {"ok": result.get("ok"), "exit_code": result.get("exit_code")})
    return result


if __name__ == "__main__":
    main.mcp.run(transport="http", host="0.0.0.0", port=8000)
