"""Check actual FastMCP schema/dispatch of the VIA-CODE-01 executor without egress."""
import json
import unittest
from types import SimpleNamespace

from fastmcp import FastMCP, Client
from via_code_pilot_tool import register


class ViaCodePilotMcpRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_mcp_registration_and_deny_by_default(self):
        mcp = FastMCP("isolated-via-code-probe")
        def forbidden(*args, **kwargs):
            raise AssertionError("denied call reached filesystem or Docker")
        core = SimpleNamespace(_project_paths=forbidden, _audit=forbidden)
        register(mcp, core)
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = [t.name for t in tools]
            self.assertEqual(names.count("project_roteia_via_code_pilot_execute"), 1)
            schema = next(t.inputSchema for t in tools if t.name == "project_roteia_via_code_pilot_execute")
            self.assertTrue({"project_id", "experiment_id"} <= set(schema.get("required", [])))
            result = await client.call_tool("project_roteia_via_code_pilot_execute", {
                "project_id": "roteia-ai-lab", "experiment_id": "VIA-CODE-01",
            })
            payload = json.loads("".join(c.text for c in result.content if hasattr(c, "text")))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error"], "confirmation_required")
            wrong = await client.call_tool("project_roteia_via_code_pilot_execute", {
                "project_id": "via", "experiment_id": "VIA-CODE-01", "confirm": "EXECUTAR",
            })
            payload = json.loads("".join(c.text for c in wrong.content if hasattr(c, "text")))
            self.assertEqual(payload["error"], "experiment_or_project_not_allowed")


if __name__ == "__main__":
    unittest.main()
