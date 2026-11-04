"""Roteia delegate adapter for HML. Provider transport is injected by runtime."""
from __future__ import annotations

from typing import Any, Callable

from ai_work_delegate import DelegateLedger, DelegateRequest, ai_work_delegate


def delegate_via_roteia(
    experiment_id: str,
    prompt: str,
    max_charge_cents: int,
    ledger_path: str,
    provider_call: Callable[[DelegateRequest], dict[str, Any]],
) -> dict[str, Any]:
    request = DelegateRequest(
        experiment_id=experiment_id,
        prompt=prompt,
        max_charge_cents=max_charge_cents,
        environment="hml",
    )
    return ai_work_delegate(request, DelegateLedger(ledger_path), transport=provider_call)
