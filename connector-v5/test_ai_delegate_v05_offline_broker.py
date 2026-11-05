"""Offline v0.5 broker and FastMCP wiring tests; no external API or charge."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_delegate_v05_offline_broker import OfflineBroker
from ai_work_delegate_candidate import register


class FakeMcp:
    def tool(self, **kwargs):
        return lambda fn: fn


def request(task_id="viaaudit_20261105"):
    return {
        "task_id": task_id, "project": "via", "environment": "hml",
        "scope": "code_review", "instruction": "Read-only Android review",
        "model": "mock", "budget_brl": 0, "context_ref": "via"
    }


class OfflineBrokerTests(unittest.TestCase):
    def test_repeated_request_is_idempotent_across_connections(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "tasks.sqlite")
            first = OfflineBroker(path).submit(request())
            second = OfflineBroker(path).submit(request())
            self.assertEqual(first, second)
            self.assertEqual(first["status"], "mock_completed")
            self.assertFalse(first["provider_invoked"])
            self.assertEqual(first["cost_brl"], 0)

    def test_conflicting_task_id_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            broker = OfflineBroker(str(Path(temp) / "tasks.sqlite"))
            self.assertEqual(broker.submit(request())["status"], "mock_completed")
            changed = {**request(), "instruction": "Different content"}
            self.assertEqual(broker.submit(changed)["status"], "idempotency_conflict")

    def test_no_paid_models_or_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            broker = OfflineBroker(str(Path(temp) / "tasks.sqlite"))
            self.assertEqual(broker.submit({**request(), "model": "anthropic/claude-sonnet-5.5"})["status"], "forbidden")
            self.assertEqual(broker.submit({**request(), "budget_brl": 1})["status"], "paid_calls_disabled")

    def test_no_production(self):
        with tempfile.TemporaryDirectory() as temp:
            broker = OfflineBroker(str(Path(temp) / "tasks.sqlite"))
            self.assertEqual(broker.submit({**request(), "environment": "production"})["status"], "forbidden")

    def test_opt_in_mock_dispatch_and_default_disabled(self):
        run = register(FakeMcp())
        payload = request()
        with patch.dict(os.environ, {"AI_DELEGATE_MODE": ""}):
            self.assertEqual(run(**payload)["status"], "operational_broker_not_configured")
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {
                "AI_DELEGATE_MODE": "mock_hml",
                "AI_DELEGATE_DB": str(Path(temp) / "tasks.sqlite")
            }):
                result = run(**payload)
                self.assertEqual(result["status"], "mock_completed")
                self.assertFalse(result["provider_invoked"])


if __name__ == "__main__":
    unittest.main()
