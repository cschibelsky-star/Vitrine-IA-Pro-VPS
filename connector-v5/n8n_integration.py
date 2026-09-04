from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

N8N_INTERNAL_BASE = os.getenv("N8N_INTERNAL_BASE_URL", "http://vitrine_n8n:5678").rstrip("/")
N8N_PUBLIC_URL = os.getenv("N8N_PUBLIC_URL", "https://automacoes.vitrineiapro.com.br").rstrip("/")
N8N_API_KEY = os.getenv("N8N_API_KEY", "").strip()
N8N_DOCS_MCP_URL = os.getenv("N8N_DOCS_MCP_URL", "https://n8n.mcp.kapa.ai").strip()
N8N_DOCS_GUIDE_URL = os.getenv("N8N_DOCS_GUIDE_URL", "https://docs.n8n.io/gitbook/mcp").strip()


def _request_json(path: str, *, api_key: str = "", timeout: int = 10) -> tuple[int, Any]:
    headers = {"Accept": "application/json", "User-Agent": "vitrine-mcp-v5/n8n-readonly"}
    if api_key:
        headers["X-N8N-API-KEY"] = api_key
    req = urllib.request.Request(f"{N8N_INTERNAL_BASE}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                return response.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return response.status, {"raw": raw[:500]}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, {"error": "http_error", "body": raw[:500]}
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, {"error": type(exc).__name__}


def register_n8n_tools(mcp: Any, audit: Any) -> None:
    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def n8n_integration_status() -> dict[str, Any]:
        result = {
            "ok": True,
            "mode": "read_only",
            "internal_base": N8N_INTERNAL_BASE,
            "public_url": N8N_PUBLIC_URL,
            "api_key_configured": bool(N8N_API_KEY),
            "docs_mcp": {
                "server_url": N8N_DOCS_MCP_URL,
                "guide_url": N8N_DOCS_GUIDE_URL,
                "purpose": "official_n8n_documentation",
            },
            "allowed_operations": ["health", "list_workflows"],
            "write_operations_enabled": False,
        }
        audit("n8n_integration_status", {}, {"ok": True, "api_key_configured": bool(N8N_API_KEY)})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def n8n_health() -> dict[str, Any]:
        status, payload = _request_json("/healthz")
        ok = 200 <= status < 300
        result = {"ok": ok, "status_code": status, "public_url": N8N_PUBLIC_URL, "detail": payload}
        audit("n8n_health", {}, {"ok": ok, "status_code": status})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def n8n_workflows_list(limit: int = 20, active: bool | None = None) -> dict[str, Any]:
        if not N8N_API_KEY:
            return {"ok": False, "error": "n8n_api_key_not_configured", "write_operations_enabled": False}
        limit = max(1, min(int(limit), 100))
        params: dict[str, str] = {"limit": str(limit)}
        if active is not None:
            params["active"] = "true" if active else "false"
        status, payload = _request_json(f"/api/v1/workflows?{urllib.parse.urlencode(params)}", api_key=N8N_API_KEY)
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        sanitized = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            sanitized.append({
                "id": row.get("id"),
                "name": row.get("name"),
                "active": row.get("active"),
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
                "tags": row.get("tags", []),
            })
        ok = 200 <= status < 300
        result = {"ok": ok, "status_code": status, "count": len(sanitized), "workflows": sanitized}
        if not ok:
            result["error"] = payload.get("error", "n8n_api_request_failed") if isinstance(payload, dict) else "n8n_api_request_failed"
        audit("n8n_workflows_list", {"limit": limit, "active": active}, {"ok": ok, "status_code": status, "count": len(sanitized)})
        return result
