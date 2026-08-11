from __future__ import annotations

import os
import platform
from datetime import datetime, timezone
from typing import Any

from project_registry import get_project_context, list_project_contexts

CONNECTOR_ID = "vitrine_ops"
CONNECTOR_DISPLAY_NAME = "Vitrine IA Pro — Centro Operacional"
CONNECTOR_VERSION = "2.1.0-stabilization.1"
REGISTRY_VERSION = "2026-08-11.1"


def connector_health() -> dict[str, Any]:
    """Health determinístico do runtime, sem depender de um projeto específico."""
    return {
        "ok": True,
        "connector_id": CONNECTOR_ID,
        "display_name": CONNECTOR_DISPLAY_NAME,
        "version": CONNECTOR_VERSION,
        "registry_version": REGISTRY_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "ops_broker_url": os.getenv("OPS_BROKER_URL", "http://ops_broker:8770").rstrip("/"),
        "projects": list_project_contexts()["projects"],
    }


def project_context(project_id: str) -> dict[str, Any]:
    """Retorna caminhos e parâmetros canônicos do projeto solicitado."""
    return get_project_context(project_id)
