"""v0.5 broker-side mock executor for HML; no external provider, shell or writes.

Separate from MCP transport. All responses explicitly identify simulation.
Production inference requires a separately reviewed authorization and budget ledger.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path

SCOPES = frozenset({"analysis", "code_review", "code_generate"})
TASK_ID = re.compile(r"^[A-Za-z0-9_-]{8,100}$")


def _digest(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class OfflineBroker:
    def __init__(self, db_path: str, *, allowed_projects: frozenset[str] = frozenset({"via"})):
        self.db_path = str(db_path)
        self.allowed_projects = allowed_projects
        if not Path(self.db_path).parent.is_dir():
            raise RuntimeError("delegate_storage_not_configured")
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.execute("PRAGMA busy_timeout = 10000")
            db.execute(
                "CREATE TABLE IF NOT EXISTS delegate_tasks ("
                "task_id TEXT PRIMARY KEY, digest TEXT NOT NULL, "
                "status TEXT NOT NULL, result TEXT NOT NULL)"
            )
            db.commit()

    def submit(self, request: dict) -> dict:
        if not isinstance(request, dict):
            return {"ok": False, "status": "invalid_request"}
        task_id = request.get("task_id")
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            return {"ok": False, "status": "invalid_task_id"}
        if (request.get("project") not in self.allowed_projects or
            request.get("environment") != "hml" or
            request.get("scope") not in SCOPES or
            request.get("model") != "mock"):
            return {"ok": False, "status": "forbidden"}
        instruction = request.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 40000:
            return {"ok": False, "status": "invalid_request"}
        if request.get("budget_brl") != 0 or isinstance(request.get("budget_brl"), bool):
            return {"ok": False, "status": "paid_calls_disabled"}
        digest = _digest(request)
        run_id = str(uuid.uuid4())
        pending = {"ok": False, "status": "uncertain_no_retry", "mode": "mock",
                   "provider_invoked": False, "task_id": task_id, "run_id": run_id}
        with sqlite3.connect(self.db_path, timeout=10, isolation_level=None) as db:
            db.execute("PRAGMA busy_timeout = 10000")
            db.execute("BEGIN IMMEDIATE")
            found = db.execute(
                "SELECT digest, result FROM delegate_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if found is not None:
                db.commit()
                return json.loads(found[1]) if found[0] == digest else {
                    "ok": False, "status": "idempotency_conflict", "task_id": task_id
                }
            db.execute(
                "INSERT INTO delegate_tasks VALUES (?, ?, ?, ?)",
                (task_id, digest, "pending", json.dumps(pending))
            )
            db.commit()
        result = {
            "ok": True, "status": "mock_completed", "mode": "mock",
            "provider_invoked": False, "cost_brl": 0,
            "task_id": task_id, "run_id": run_id,
            "text": "OFFLINE SIMULATION ONLY. Claude/Roteia was not called."
        }
        with sqlite3.connect(self.db_path, timeout=10) as db:
            db.execute(
                "UPDATE delegate_tasks SET status=?, result=? "
                "WHERE task_id=? AND digest=? AND status='pending'",
                ("completed", json.dumps(result), task_id, digest)
            )
            db.commit()
        return result
