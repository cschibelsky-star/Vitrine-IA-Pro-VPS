from __future__ import annotations

import os
from typing import Any

import httpx

OPS_BROKER_URL = os.getenv("OPS_BROKER_URL", "http://ops_broker:8770").rstrip("/")
OPS_BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
OPS_REQUEST_TIMEOUT = float(os.getenv("OPS_REQUEST_TIMEOUT", "120"))


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {OPS_BROKER_TOKEN}"}
    with httpx.Client(timeout=OPS_REQUEST_TIMEOUT) as client:
        response = client.request(
            method,
            f"{OPS_BROKER_URL}{path}",
            headers=headers,
            json=payload if method != "GET" else None,
        )
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:2000]}
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code, "body": body}
    return body


def via_health() -> dict[str, Any]:
    return _request("GET", "/via/health")


def via_list_files(path: str = ".", max_entries: int = 500) -> dict[str, Any]:
    return _request("POST", "/via/list-files", {"path": path, "max_entries": max_entries})


def via_read_file(path: str, max_bytes: int = 100000) -> dict[str, Any]:
    return _request("POST", "/via/read-file", {"path": path, "max_bytes": max_bytes})


def via_write_file(path: str, content: str, confirm: str = "") -> dict[str, Any]:
    return _request("POST", "/via/write-file", {"path": path, "content": content, "confirm": confirm})


def via_execute_command(command: list[str], cwd: str = ".", timeout: int = 300, confirm: str = "") -> dict[str, Any]:
    return _request("POST", "/via/execute-command", {"command": command, "cwd": cwd, "timeout": timeout, "confirm": confirm})
