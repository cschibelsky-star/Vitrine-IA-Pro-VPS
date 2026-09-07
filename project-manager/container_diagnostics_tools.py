from __future__ import annotations

from typing import Any

from project_manager_tools import _request


def container_status(name: str) -> dict[str, Any]:
    return _request("GET", f"/containers/{name}/status")


def container_logs(name: str, tail: int = 200) -> dict[str, Any]:
    bounded = max(1, min(int(tail), 500))
    return _request("GET", f"/containers/{name}/logs?tail={bounded}")
