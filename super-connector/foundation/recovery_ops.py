from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import main

ROUTING_PROJECT_ID = "vitrine-super-centro-operacional-candidate-https"
ALLOWED_DOMAIN_SUFFIX = ".vitrineiapro.com.br"


def _safe_hostname(hostname: str) -> str:
    value = str(hostname or "").strip().lower().rstrip(".")
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789.-"
    if not value or any(ch not in allowed for ch in value):
        raise ValueError("invalid_hostname")
    if not value.endswith(ALLOWED_DOMAIN_SUFFIX):
        raise PermissionError("hostname_not_allowed")
    return value


def _safe_route_id(route_id: str) -> str:
    value = str(route_id or "").strip().lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    if not value or any(ch not in allowed for ch in value):
        raise ValueError("invalid_route_id")
    return value


def _routing_repository() -> Path:
    project = main._load_project(ROUTING_PROJECT_ID)
    repository = main._repository(project)
    registry = repository / "routing" / "routes.json"
    if not registry.is_file():
        raise FileNotFoundError("routing_registry_missing")
    return repository


def _load_route(route_id: str) -> tuple[Path, dict[str, Any]]:
    normalized = _safe_route_id(route_id)
    repository = _routing_repository()
    registry = repository / "routing" / "routes.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    route = next((item for item in data.get("routes", []) if item.get("id") == normalized), None)
    if route is None:
        raise FileNotFoundError("route_not_registered")
    return repository, route


def connector_endpoint_check(hostname: str, path: str = "/mcp") -> dict[str, Any]:
    try:
        host = _safe_hostname(hostname)
    except (ValueError, PermissionError) as exc:
        return {"ok": False, "error": str(exc)}
    route_path = str(path or "/mcp").strip()
    if not route_path.startswith("/") or ".." in route_path.split("/") or len(route_path) > 200:
        return {"ok": False, "error": "invalid_endpoint_path"}
    url = f"https://{host}{route_path}"
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json, text/event-stream", "User-Agent": "vitrine-super-recovery/0.3"})
    try:
        with urllib.request.urlopen(request, timeout=12, context=ssl.create_default_context()) as response:
            status = int(response.status)
            return {"ok": True, "reachable": True, "hostname": host, "path": route_path, "status_code": status, "content_type": str(response.headers.get("content-type", ""))}
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        reachable = 100 <= status < 600
        return {"ok": reachable, "reachable": reachable, "hostname": host, "path": route_path, "status_code": status, "content_type": str(exc.headers.get("content-type", "")) if exc.headers else "", "auth_expected": status in {401, 403}}
    except urllib.error.URLError as exc:
        return {"ok": False, "reachable": False, "hostname": host, "path": route_path, "error": "endpoint_unreachable", "detail": type(exc.reason).__name__}
    except (TimeoutError, OSError) as exc:
        return {"ok": False, "reachable": False, "hostname": host, "path": route_path, "error": "endpoint_probe_failed", "detail": type(exc).__name__}


def _inspect_one(container_id: str) -> dict[str, Any] | None:
    inspected = main._run(["docker", "inspect", container_id], Path("/"), timeout=30)
    if not inspected.get("ok"):
        return None
    try:
        data = json.loads(str(inspected.get("stdout", "[]")))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    return data[0]


def proxy_route_inspect(hostname: str) -> dict[str, Any]:
    try:
        host = _safe_hostname(hostname)
    except (ValueError, PermissionError) as exc:
        return {"ok": False, "error": str(exc)}
    listed = main._run(["docker", "ps", "-aq", "--no-trunc"], Path("/"), timeout=30)
    if not listed.get("ok"):
        return {"ok": False, "error": "docker_list_failed", "detail": listed}
    ids = [line.strip() for line in str(listed.get("stdout", "")).splitlines() if line.strip()]
    if not ids:
        return {"ok": True, "hostname": host, "matches": [], "match_count": 0, "inspect_failures": 0}

    matches: list[dict[str, Any]] = []
    inspect_failures = 0
    for container_id in ids:
        item = _inspect_one(container_id)
        if item is None:
            inspect_failures += 1
            continue
        labels = item.get("Config", {}).get("Labels", {}) or {}
        matched = {key: value for key, value in labels.items() if host in str(value)}
        if not matched:
            continue
        networks = sorted((item.get("NetworkSettings", {}).get("Networks", {}) or {}).keys())
        matches.append({"container": str(item.get("Name", "")).lstrip("/"), "running": bool(item.get("State", {}).get("Running")), "status": item.get("State", {}).get("Status"), "networks": networks, "labels": matched})
    return {"ok": True, "hostname": host, "matches": matches, "match_count": len(matches), "inspect_failures": inspect_failures, "inspected_count": len(ids)}


def mcp_publication_check(hostname: str, container: str = "") -> dict[str, Any]:
    endpoint = connector_endpoint_check(hostname, "/mcp")
    proxy = proxy_route_inspect(hostname)
    runtime: dict[str, Any] | None = None
    container_name = str(container or "").strip()
    if container_name:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        if any(ch not in allowed for ch in container_name):
            return {"ok": False, "error": "invalid_container_name"}
        item = _inspect_one(container_name)
        if item is not None:
            health = item.get("State", {}).get("Health", {}) or {}
            runtime = {"container": container_name, "running": bool(item.get("State", {}).get("Running")), "status": item.get("State", {}).get("Status"), "health": health.get("Status"), "networks": sorted((item.get("NetworkSettings", {}).get("Networks", {}) or {}).keys())}
        else:
            runtime = {"container": container_name, "error": "container_not_found_or_invalid"}
    ok = bool(endpoint.get("reachable")) and bool(proxy.get("ok")) and bool(proxy.get("match_count", 0))
    if runtime is not None:
        ok = ok and bool(runtime.get("running"))
    return {"ok": ok, "endpoint": endpoint, "proxy": proxy, "runtime": runtime}


def hml_route_inspect(route_id: str) -> dict[str, Any]:
    try:
        _, route = _load_route(route_id)
        normalized = _safe_route_id(route_id)
        host = _safe_hostname(str(route.get("hostname", "")))
    except (FileNotFoundError, ValueError, PermissionError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc), "route_id": str(route_id or "")}
    carrier = f"vitrine_route_{normalized}"
    item = _inspect_one(carrier)
    carrier_state: dict[str, Any] | None = None
    if item is not None:
        carrier_state = {"container": carrier, "running": bool(item.get("State", {}).get("Running")), "status": item.get("State", {}).get("Status"), "networks": sorted((item.get("NetworkSettings", {}).get("Networks", {}) or {}).keys())}
    return {"ok": True, "route_id": normalized, "hostname": host, "route": route, "carrier": carrier_state, "proxy": proxy_route_inspect(host)}


def hml_route_activate(route_id: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    try:
        repository, route = _load_route(route_id)
        normalized = _safe_route_id(route_id)
        _safe_hostname(str(route.get("hostname", "")))
    except (FileNotFoundError, ValueError, PermissionError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc), "route_id": str(route_id or "")}
    if route.get("environment") != "homologation":
        return {"ok": False, "error": "route_environment_not_allowed", "route_id": normalized}
    if route.get("ssl") is not True:
        return {"ok": False, "error": "route_ssl_required", "route_id": normalized}
    if route.get("status") not in {"pending_dns_proxy", "active"}:
        return {"ok": False, "error": "route_status_not_publishable", "route_id": normalized, "status": route.get("status")}
    script = repository / "routing" / "activate_single_hml_route.sh"
    if not script.is_file():
        return {"ok": False, "error": "route_activation_script_missing"}
    result = main._run(["bash", str(script), str(repository)], repository, timeout=1200, input_text=None)
    if result.get("exit_code") == 0 and "ROUTE_ACTIVE" in str(result.get("stdout", "")):
        return {**result, "route_id": normalized, "hostname": route.get("hostname"), "upstream": route.get("upstream")}
    env_result = main._run(["env", f"ROUTE_ID={normalized}", "bash", str(script), str(repository)], repository, timeout=1200)
    return {**env_result, "route_id": normalized, "hostname": route.get("hostname"), "upstream": route.get("upstream")}
