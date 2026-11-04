"""Fail-closed registration of the reusable Claude delegation tool in isolated HML.

No network, shell, provider credential or paid inference is reachable from this
adapter. A reviewed operational broker will replace the disabled handler later.
"""
from __future__ import annotations

import re
from typing import Any

TASK_ID = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
ALLOWED_SCOPES = frozenset({"code_generate", "code_review", "analysis"})


def register(mcp: Any) -> Any:
    """Expose a real, discoverable FastMCP tool while keeping execution off."""
    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def ai_work_delegate(
        task_id: str,
        project: str,
        environment: str,
        scope: str,
        instruction: str,
        model: str = "anthropic/claude-sonnet-5.5",
        budget_brl: float = 0.0,
        context_ref: str = "",
    ) -> dict[str, Any]:
        """Delegate an authorized programming task (disabled in candidate HML)."""
        if not TASK_ID.fullmatch(task_id):
            return {"ok": False, "status": "invalid_task_id"}
        if environment != "hml" or scope not in ALLOWED_SCOPES:
            return {"ok": False, "status": "forbidden"}
        if not instruction.strip() or len(instruction) > 40000:
            return {"ok": False, "status": "invalid_request"}
        return {
            "ok": False,
            "status": "operational_broker_not_configured",
            "task_id": task_id,
            "project": project,
            "detail": "No provider call made; identity, atomic budget and broker integration pending.",
        }
    return ai_work_delegate
