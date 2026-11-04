"""Offline safety and MCP registration checks for ai_work_delegate candidate."""
import unittest
from ai_work_delegate_candidate import register


class FakeMcp:
    def __init__(self):
        self.tools = {}

    def tool(self, **kwargs):
        def decorate(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorate


class AiWorkDelegateCandidateTests(unittest.TestCase):
    def setUp(self):
        self.mcp = FakeMcp()
        register(self.mcp)
        self.call = self.mcp.tools["ai_work_delegate"]
        self.base = {
            "task_id": "viaaudit_20261104",
            "project": "via",
            "environment": "hml",
            "scope": "code_review",
            "instruction": "Audit Android voice capture without editing code",
        }

    def test_registered_exactly_once(self):
        self.assertEqual(list(self.mcp.tools), ["ai_work_delegate"])

    def test_broker_unconfigured_and_no_paid_calls(self):
        result = self.call(**self.base)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "operational_broker_not_configured")

    def test_invalid_task_id_rejected(self):
        result = self.call(**{**self.base, "task_id": "../../unsafe"})
        self.assertEqual(result["status"], "invalid_task_id")

    def test_production_rejected(self):
        result = self.call(**{**self.base, "environment": "production"})
        self.assertEqual(result["status"], "forbidden")

    def test_unknown_scope_rejected(self):
        result = self.call(**{**self.base, "scope": "deploy"})
        self.assertEqual(result["status"], "forbidden")

    def test_empty_instruction_rejected(self):
        result = self.call(**{**self.base, "instruction": "  "})
        self.assertEqual(result["status"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
