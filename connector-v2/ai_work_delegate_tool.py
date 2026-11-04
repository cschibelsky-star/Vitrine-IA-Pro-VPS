"""MCP-facing entrypoints for ai_work_delegate (HML only).

Pure functions: the tools are registered only in the installed main.py, by
install_ai_work_delegate.py. This module never registers MCP tools itself.

The budget ledger must live on a persistent volume OUTSIDE the tree that the release
updater backs up and restores, and outside the image filesystem. Otherwise a rebuild
or a rollback would silently reset the R$10 cap and the duplicate-charge guard.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from ai_work_delegate import MAX_TOTAL_CENTS, DelegateBlocked, DelegateLedger
from roteia_delegate_adapter import delegate_via_roteia
from roteia_transport import RoteiaTransport, inspect_config, load_config

LEDGER_ENV = "AI_WORK_DELEGATE_LEDGER"
DEFAULT_LEDGER = "/data/ai-work-delegate/ledger.sqlite"
# /app is the image filesystem (lost on rebuild); the connector root is what the updater
# backs up and restores. Neither may hold the ledger.
FORBIDDEN_ROOTS = ("/srv/connectors/vitrine-vps-mcp", "/app")
DEFAULT_REQUEST_CENTS = 100
CONFIRM_TOKEN = "EXECUTAR"


def resolve_ledger_path(
    env: Mapping[str, str] | None = None,
    *,
    require_mount: bool = True,
    forbidden_roots: tuple[str, ...] = FORBIDDEN_ROOTS,
) -> Path:
    env = os.environ if env is None else env
    path = Path((env.get(LEDGER_ENV) or DEFAULT_LEDGER).strip())
    if not path.is_absolute():
        raise DelegateBlocked("ledger_path_not_absolute")
    parent = path.parent.resolve()
    if not parent.is_dir():
        raise DelegateBlocked("ledger_dir_missing")
    for root in forbidden_roots:
        forbidden = Path(root).resolve()
        if parent == forbidden or forbidden in parent.parents:
            raise DelegateBlocked("ledger_in_restorable_tree")
    if require_mount and not os.path.ismount(parent):
        raise DelegateBlocked("ledger_not_on_persistent_volume")
    return parent / path.name


def run_delegate(
    experiment_id: str,
    prompt: str,
    max_charge_cents: int = DEFAULT_REQUEST_CENTS,
    confirm: str = "",
    *,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[[], Any] | None = None,
    require_mount: bool = True,
    forbidden_roots: tuple[str, ...] = FORBIDDEN_ROOTS,
) -> dict[str, Any]:
    if confirm != CONFIRM_TOKEN:
        return {"ok": False, "error": "confirmation_required", "required": CONFIRM_TOKEN}
    try:
        ledger_path = resolve_ledger_path(env, require_mount=require_mount, forbidden_roots=forbidden_roots)
        transport = RoteiaTransport(load_config(env), client_factory)
        return delegate_via_roteia(experiment_id, prompt, max_charge_cents, str(ledger_path), transport)
    except DelegateBlocked as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:  # never leak provider/internal detail (headers, URLs) to the caller
        return {"ok": False, "error": "internal_error"}


def delegate_status(
    env: Mapping[str, str] | None = None,
    *,
    require_mount: bool = True,
    forbidden_roots: tuple[str, ...] = FORBIDDEN_ROOTS,
) -> dict[str, Any]:
    """Readiness report. Contains stable codes and counters only, never secrets."""
    ledger: dict[str, Any] = {"ready": False}
    try:
        path = resolve_ledger_path(env, require_mount=require_mount, forbidden_roots=forbidden_roots)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".write-probe-"):
            pass
        ledger.update(DelegateLedger(path).status())
        ledger["ready"] = True
    except DelegateBlocked as exc:
        ledger["error"] = str(exc)
    except Exception:
        ledger["error"] = "ledger_unavailable"
    _, problems = inspect_config(env)
    roteia = {"ready": not problems, "problems": problems}
    return {
        "ok": True,
        "environment": "hml",
        "ready_for_paid_call": bool(ledger["ready"] and roteia["ready"]),
        "ledger": ledger,
        "roteia": roteia,
        "caps": {"total_cents": MAX_TOTAL_CENTS, "default_request_cents": DEFAULT_REQUEST_CENTS},
    }


def ai_work_delegate_tool(
    experiment_id: str, prompt: str, max_charge_cents: int = DEFAULT_REQUEST_CENTS, confirm: str = ""
) -> dict[str, Any]:
    return run_delegate(experiment_id, prompt, max_charge_cents, confirm)


def ai_work_delegate_status() -> dict[str, Any]:
    return delegate_status()
