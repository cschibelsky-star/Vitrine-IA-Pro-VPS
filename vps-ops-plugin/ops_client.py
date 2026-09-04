from __future__ import annotations

import os
from typing import Any

import httpx

OPS_API_URL = os.getenv("OPS_API_URL", "http://host.docker.internal:18080").rstrip("/")
OPS_BROKER_URL = os.getenv("OPS_BROKER_URL", "http://ops_broker:8770").rstrip("/")
OPS_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
OPS_TIMEOUT = float(os.getenv("OPS_REQUEST_TIMEOUT", "1200"))


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if OPS_TOKEN:
        headers["Authorization"] = f"Bearer {OPS_TOKEN}"
    return headers


def _request(base: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=OPS_TIMEOUT) as client:
            response = client.request(method, f"{base}{path}", headers=_headers(), json=payload)
    except httpx.HTTPError as exc:
        return {"ok": False, "error": "upstream_unreachable", "detail": type(exc).__name__, "path": path}

    try:
        body: Any = response.json()
    except ValueError:
        body = {"detail": response.text[:2000]}

    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code, "body": body, "path": path}
    return body if isinstance(body, dict) else {"ok": True, "data": body}


def api(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _request(OPS_API_URL, method, path, payload)


def broker(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _request(OPS_BROKER_URL, method, path, payload)


def project_status(project_id: str) -> dict[str, Any]:
    return api("GET", f"/projects/{project_id}/status")


def project_read(project_id: str, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:
    return api(
        "POST",
        "/projects/read-file",
        {"project_id": project_id, "path": path, "start_line": start_line, "end_line": end_line},
    )


def project_shared_read(project_id: str, shared_directory: str, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:
    return api(
        "POST",
        "/projects/shared/read",
        {
            "project_id": project_id,
            "shared_directory": shared_directory,
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
        },
    )


def server_health() -> dict[str, Any]:
    return api("GET", "/health")


def mcp_maintenance(action: str) -> dict[str, Any]:
    if action not in {"status", "health", "restart"}:
        return {"ok": False, "error": "unsupported_action"}
    return broker("POST", "/maintenance/mcp", {"action": action})
