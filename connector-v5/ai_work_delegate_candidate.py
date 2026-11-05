"""Isolated HML FastMCP adapter. Provider inference is disabled.

Set AI_DELEGATE_MODE=mock_hml to enable only local offline simulation. The
default deliberately refuses all tasks. No shell, API key or provider calls.
"""
from __future__ import annotations

import os
import re
from typing import Any

TASK_ID = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
ALLOWED_SCOPES = frozenset({"code_generate", "code_review", "analysis"})


def register(mcp: Any) -> Any:
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
        """Delegate programming work; only isolated mock HML is enabled."""
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            return {"ok": False, "status": "invalid_task_id"}
        if environment != "hml" or scope not in ALLOWED_SCOPES or project != "via":
            return {"ok": False, "status": "forbidden"}
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 40000:
            return {"ok": False, "status": "invalid_request"}
        if not isinstance(context_ref, str) or len(context_ref) > 200:
            return {"ok": False, "status": "invalid_context"}
        if model != "mock" or budget_brl != 0 or type(budget_brl) is bool:
            return {"ok": False, "status": "paid_calls_disabled"}
        if os.environ.get("AI_DELEGATE_MODE") != "mock_hml":
            return {"ok": False, "status": "operational_broker_not_configured"}
        from ai_delegate_v05_offline_broker import OfflineBroker
        database = os.environ.get("AI_DELEGATE_DB", "")
        if not database:
            return {"ok": False, "status": "delegate_storage_not_configured"}
        try:
            broker = OfflineBroker(database)
            return broker.submit({
                "task_id": task_id, "project": project, "environment": environment,
                "scope": scope, "instruction": instruction, "model": model,
                "budget_brl": budget_brl, "context_ref": context_ref,
            })
        except (OSError, ValueError, RuntimeError):
            return {"ok": False, "status": "delegate_storage_unavailable"}
    return ai_work_delegate
