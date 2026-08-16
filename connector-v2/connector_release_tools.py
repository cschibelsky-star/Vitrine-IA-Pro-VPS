from __future__ import annotations

import os
from typing import Any

import httpx

OPS_BROKER_URL = os.getenv("OPS_BROKER_URL", "http://ops_broker:8770").rstrip("/")
OPS_BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
OPS_REQUEST_TIMEOUT = float(os.getenv("OPS_REQUEST_TIMEOUT", "1200"))


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {OPS_BROKER_TOKEN}"}
    with httpx.Client(timeout=OPS_REQUEST_TIMEOUT) as client:
        response = client.post(
            f"{OPS_BROKER_URL}{path}",
            headers=headers,
            json=payload,
        )
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:2000]}
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code, "body": body}
    return body


def connector_update_release(branch: str, confirm: str = "") -> dict[str, Any]:
    return _post(
        "/connector-release/update",
        {"branch": branch, "confirm": confirm},
    )


def connector_update_status(job_id: str) -> dict[str, Any]:
    return _post(
        "/connector-release/status",
        {"job_id": job_id},
    )
