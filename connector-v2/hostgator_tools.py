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


def hostgator_health() -> dict[str, Any]:
    return _request("GET", "/hostgator/health")


def hostgator_git_status(root: str) -> dict[str, Any]:
    return _request("POST", "/hostgator/git/status", {"root": root})


def hostgator_git_compare(root: str) -> dict[str, Any]:
    return _request("POST", "/hostgator/git/compare", {"root": root})


def hostgator_read_file(root: str, path: str, max_bytes: int = 100000) -> dict[str, Any]:
    return _request("POST", "/hostgator/read-file", {"root": root, "path": path, "max_bytes": max_bytes})
