"""Verify that the Docker image loads the isolated MCP tool exactly once."""
import unittest
from pathlib import Path


class ViaCodePilotWiringTests(unittest.TestCase):
    def test_guard_stage_registers_and_copies_narrow_tool(self):
        root = Path(__file__).resolve().parents[1]
        entry = (root / "guard-stage-20261010/main_ext.py").read_text()
        docker = (root / "guard-stage-20261010/Dockerfile").read_text()
        self.assertEqual(entry.count("register_via_code_pilot(mcp, core)"), 1)
        self.assertIn("COPY connector-v5/via_code_pilot_tool.py /app/via_code_pilot_tool.py", docker)
        self.assertIn("from via_code_pilot_tool import register", entry)


if __name__ == "__main__":
    unittest.main()
