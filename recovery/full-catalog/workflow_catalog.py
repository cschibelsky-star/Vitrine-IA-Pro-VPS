from __future__ import annotations

import json
import os
from typing import Any

from server import mcp

CATALOG_ENV = "N8N_WORKFLOW_CATALOG_JSON"


def _catalog() -> dict[str, dict[str, Any]]:
    raw = os.getenv(CATALOG_ENV, "{}").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"__error__": {"description": f"Catálogo inválido: {exc}"}}
    if not isinstance(parsed, dict):
        return {"__error__": {"description": "O catálogo deve ser um objeto JSON."}}
    safe: dict[str, dict[str, Any]] = {}
    for name, item in parsed.items():
        if not isinstance(name, str) or not isinstance(item, dict):
            continue
        safe[name] = {
            "description": str(item.get("description", "")),
            "method": str(item.get("method", "POST")).upper(),
            "path": str(item.get("path", "")),
            "enabled": bool(item.get("enabled", False)),
            "category": str(item.get("category", "general")),
        }
    return safe


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def n8n_workflow_catalog() -> dict[str, Any]:
    catalog = _catalog()
    return {
        "configured": bool(catalog) and "__error__" not in catalog,
        "count": len([name for name in catalog if name != "__error__"]),
        "workflows": catalog,
        "execution_policy": "Somente aliases habilitados podem ser executados; toda execução exige confirm='EXECUTAR'.",
    }


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def n8n_workflow_plan(alias: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    item = _catalog().get(alias)
    if not item:
        return {"ok": False, "error": "workflow_not_cataloged", "alias": alias}
    if not item.get("enabled"):
        return {"ok": False, "error": "workflow_disabled", "alias": alias, "workflow": item}
    return {
        "ok": True,
        "mode": "plan_only",
        "alias": alias,
        "workflow": item,
        "payload_keys": sorted((payload or {}).keys()),
        "requires_confirmation": True,
        "next_tool": "run_n8n_workflow",
    }
