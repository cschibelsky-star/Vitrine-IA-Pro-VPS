from __future__ import annotations

import os
from typing import Any

import httpx

OPS_BROKER_URL = os.getenv("OPS_BROKER_URL", "http://ops_broker:8770").rstrip("/")
OPS_BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
OPS_REQUEST_TIMEOUT = float(os.getenv("OPS_REQUEST_TIMEOUT", "1200"))


def _post(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {OPS_BROKER_TOKEN}"}
    with httpx.Client(timeout=OPS_REQUEST_TIMEOUT) as client:
        response = client.post(
            f"{OPS_BROKER_URL}{path}",
            headers=headers,
            json=payload or {},
        )
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:2000]}
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code, "body": body}
    return body


def tvsumare_clone_repository(
    repository_url: str = "https://github.com/cschibelsky-star/TVSUMARE_ENTERPRISE.git",
    branch: str = "main",
) -> dict[str, Any]:
    """Clona ou atualiza o repositório oficial da TV Sumaré na VPS."""
    return _post(
        "/tvsumare/migration/clone",
        {"repository_url": repository_url, "branch": branch},
    )


def tvsumare_import_hostgator_snapshot(
    remote_path: str = "public_html",
) -> dict[str, Any]:
    """Cria snapshot imutável da TV Sumaré no HostGator, sem apagar a origem."""
    return _post(
        "/tvsumare/migration/hostgator-snapshot",
        {"remote_path": remote_path},
    )
