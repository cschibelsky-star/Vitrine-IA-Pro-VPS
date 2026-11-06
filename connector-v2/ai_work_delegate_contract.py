"""Versioned, fail-closed adapter for offline delegate requests only.

This module does not register an MCP tool, access providers, or reserve funds.
"""
from __future__ import annotations

import re
from typing import Any

TASK_ID = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
SCOPES = frozenset({"analysis", "code_review", "code_generate"})


class ContractRejected(ValueError):
    pass


def normalize_mock_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize v5 mock requests or v2 experiment requests to one safe envelope."""
    if not isinstance(payload, dict):
        raise ContractRejected("invalid_request")
    if "task_id" in payload:
        task_id = payload.get("task_id")
        instruction = payload.get("instruction")
        project = payload.get("project")
        scope = payload.get("scope")
        environment = payload.get("environment")
        model = payload.get("model")
        budget = payload.get("budget_brl")
        if model != "mock" or type(budget) not in (int, float) or budget != 0:
            raise ContractRejected("paid_calls_disabled")
    else:
        task_id = payload.get("experiment_id")
        instruction = payload.get("prompt")
        project = payload.get("project")
        scope = payload.get("scope")
        environment = payload.get("environment")
        model = payload.get("model")
        cents = payload.get("max_charge_cents")
        if model != "mock" or type(cents) is not int or cents != 0:
            raise ContractRejected("paid_calls_disabled")
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise ContractRejected("invalid_task_id")
    if project != "via" or environment != "hml" or not isinstance(scope, str) or scope not in SCOPES:
        raise ContractRejected("forbidden")
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 20000:
        raise ContractRejected("invalid_instruction")
    return {"contract_version": 1, "task_id": task_id, "project": project,
            "environment": environment, "scope": scope, "instruction": instruction,
            "model": "mock", "budget_brl": 0}
