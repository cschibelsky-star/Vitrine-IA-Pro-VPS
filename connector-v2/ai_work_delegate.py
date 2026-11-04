"""Isolated, fail-closed groundwork for ai_work_delegate (HML only).

No network transport or MCP registration is enabled by this module.
A separate reviewed adapter must supply a Roteia transport and settlement evidence.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

MAX_TOTAL_CENTS = 1000
MAX_REQUEST_CENTS = 1000
MODEL = "claude-sonnet-5.5"


class DelegateBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class DelegateRequest:
    experiment_id: str
    prompt: str
    max_charge_cents: int
    environment: str = "hml"
    model: str = MODEL


def _validate(req: DelegateRequest) -> None:
    if req.environment != "hml":
        raise DelegateBlocked("production_blocked")
    if req.model != MODEL:
        raise DelegateBlocked("model_not_approved")
    if not req.experiment_id or len(req.experiment_id) > 128:
        raise DelegateBlocked("invalid_experiment_id")
    if not req.prompt or len(req.prompt) > 20000:
        raise DelegateBlocked("invalid_prompt")
    if not isinstance(req.max_charge_cents, int) or not 0 < req.max_charge_cents <= MAX_REQUEST_CENTS:
        raise DelegateBlocked("invalid_request_cap")


class DelegateLedger:
    """SQLite durable budget reservations. Uncertain charges stay reserved."""

    def __init__(self, path: str | Path):
        self.path = str(path)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("CREATE TABLE IF NOT EXISTS delegate_calls ("
                   "experiment_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, "
                   "reserved_cents INTEGER NOT NULL, status TEXT NOT NULL, "
                   "result_json TEXT)")
        return db

    def reserve(self, req: DelegateRequest) -> None:
        _validate(req)
        fingerprint = hashlib.sha256(
            json.dumps([req.model, req.prompt, req.max_charge_cents], ensure_ascii=False).encode()
        ).hexdigest()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT request_hash FROM delegate_calls WHERE experiment_id=?",
                (req.experiment_id,),
            ).fetchone()
            if existing:
                db.rollback()
                raise DelegateBlocked("duplicate_or_uncertain_charge")
            spent = db.execute(
                "SELECT COALESCE(SUM(reserved_cents),0) FROM delegate_calls"
            ).fetchone()[0]
            if spent + req.max_charge_cents > MAX_TOTAL_CENTS:
                db.rollback()
                raise DelegateBlocked("total_budget_exceeded")
            db.execute(
                "INSERT INTO delegate_calls VALUES (?,?,?,?,NULL)",
                (req.experiment_id, fingerprint, req.max_charge_cents, "reserved"),
            )
            db.commit()

    def mark_uncertain(self, experiment_id: str) -> None:
        with closing(self._connect()) as db:
            db.execute(
                "UPDATE delegate_calls SET status='charge_uncertain' "
                "WHERE experiment_id=? AND status='reserved'",
                (experiment_id,),
            )

    def status(self) -> dict[str, Any]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT status, COUNT(*), SUM(reserved_cents) FROM delegate_calls "
                "GROUP BY status"
            ).fetchall()
        reserved = sum(row[2] or 0 for row in rows)
        return {"cap_cents": MAX_TOTAL_CENTS, "reserved_cents": reserved,
                "available_cents": MAX_TOTAL_CENTS - reserved,
                "by_status": {row[0]: {"count": row[1], "cents": row[2]} for row in rows}}


def ai_work_delegate(
    request: DelegateRequest,
    ledger: DelegateLedger,
    *,
    transport: Callable[[DelegateRequest], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reserve BEFORE a call; never retry ambiguous provider failures automatically.

    Deliberately disabled until reviewed tariff, Roteia credentials status,
    settlement and a bounded transport have been verified in HML.
    """
    _validate(request)
    if transport is None:
        raise DelegateBlocked("roteia_transport_not_configured")
    # Pre-flight refusals (e.g. worst-case cost above the reservation) must happen
    # BEFORE reserving, otherwise a call that never left the machine would burn budget.
    preflight = getattr(transport, "check", None)
    if callable(preflight):
        preflight(request)
    ledger.reserve(request)
    try:
        result = transport(request)
    except Exception:
        ledger.mark_uncertain(request.experiment_id)
        raise DelegateBlocked("provider_failure_charge_possible") from None
    ledger.mark_uncertain(request.experiment_id)
    return {"ok": True, "experiment_id": request.experiment_id,
            "provider_response": result, "settlement": "pending_verification"}
