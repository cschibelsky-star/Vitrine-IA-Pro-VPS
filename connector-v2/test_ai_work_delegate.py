"""Offline safety tests for the isolated HML delegate groundwork."""
import tempfile
import unittest
from pathlib import Path
import importlib.util

MODULE = Path(__file__).with_name("ai_work_delegate.py")
spec = importlib.util.spec_from_file_location("ai_work_delegate", MODULE)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class DelegateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = mod.DelegateLedger(Path(self.temp.name) / "ledger.sqlite")

    def tearDown(self):
        self.temp.cleanup()

    def req(self, key="test-1", cents=300, **kwargs):
        return mod.DelegateRequest(key, "Return a small TypeScript function", cents, **kwargs)

    def test_disabled_without_transport_and_no_reservation(self):
        with self.assertRaisesRegex(mod.DelegateBlocked, "transport_not_configured"):
            mod.ai_work_delegate(self.req(), self.ledger)
        self.assertEqual(self.ledger.status()["reserved_cents"], 0)

    def test_production_blocked(self):
        with self.assertRaisesRegex(mod.DelegateBlocked, "production_blocked"):
            self.ledger.reserve(self.req(environment="production"))

    def test_wrong_model_blocked(self):
        with self.assertRaisesRegex(mod.DelegateBlocked, "model_not_approved"):
            self.ledger.reserve(self.req(model="other"))

    def test_boolean_charge_cap_is_rejected_without_reservation(self):
        for value in (True, False):
            with self.subTest(value=value):
                with self.assertRaisesRegex(mod.DelegateBlocked, "invalid_request_cap"):
                    self.ledger.reserve(self.req(cents=value))
        self.assertEqual(self.ledger.status()["reserved_cents"], 0)

    def test_duplicate_is_not_retried(self):
        self.ledger.reserve(self.req())
        with self.assertRaisesRegex(mod.DelegateBlocked, "duplicate"):
            self.ledger.reserve(self.req())

    def test_budget_applies_across_experiments(self):
        self.ledger.reserve(self.req("a", 700))
        with self.assertRaisesRegex(mod.DelegateBlocked, "total_budget_exceeded"):
            self.ledger.reserve(self.req("b", 400))
        self.assertEqual(self.ledger.status()["available_cents"], 300)

    def test_ambiguous_provider_failure_stays_reserved(self):
        def fail(_):
            raise RuntimeError("network_timeout")
        with self.assertRaisesRegex(mod.DelegateBlocked, "charge_possible"):
            mod.ai_work_delegate(self.req(), self.ledger, transport=fail)
        self.assertEqual(self.ledger.status()["reserved_cents"], 300)
        self.assertIn("charge_uncertain", self.ledger.status()["by_status"])

    def test_success_does_not_claim_settlement(self):
        result = mod.ai_work_delegate(self.req(), self.ledger, transport=lambda _: {"text": "ok"})
        self.assertEqual(result["settlement"], "pending_verification")
        self.assertEqual(self.ledger.status()["available_cents"], 700)


if __name__ == "__main__":
    unittest.main()
