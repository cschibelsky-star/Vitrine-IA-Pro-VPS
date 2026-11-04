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



class AiWorkDelegateFastMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_list_and_fail_closed_without_provider_call(self):
        import json
        from fastmcp import FastMCP, Client
        server = FastMCP("delegation-offline-hml")
        register(server)
        async with Client(server) as client:
            tools = await client.list_tools()
            self.assertEqual([t.name for t in tools].count("ai_work_delegate"), 1)
            result = await client.call_tool("ai_work_delegate", {
                "task_id": "viaaudit_20261104",
                "project": "via",
                "environment": "hml",
                "scope": "code_review",
                "instruction": "Read-only audit of VIA Android",
            })
            payload = json.loads("".join(part.text for part in result.content if hasattr(part, "text")))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "operational_broker_not_configured")


if __name__ == "__main__":
    unittest.main()
