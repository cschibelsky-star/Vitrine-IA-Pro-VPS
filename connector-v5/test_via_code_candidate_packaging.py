"""Candidate packaging guardrails. No Docker daemon or network required."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class ViaCodeCandidatePackagingTests(unittest.TestCase):
    def test_image_starts_from_actual_v5_fix2(self):
        docker=(ROOT/"guard-stage-20261010/Dockerfile.via-code-overlay").read_text()
        self.assertIn("FROM vitrine-v5-factory-via-hml:fix2",docker)
        self.assertNotIn("FROM vitrine-publication-guard-baseline-v5",docker)
        self.assertIn("COPY connector-v5/via_code_pilot_tool.py",docker)
        self.assertIn("COPY guard-stage-20261010/via_code_mcp_probe.py",docker)
    def test_cannot_start_existing_main_ext_as_main(self):
        entry=(ROOT/"guard-stage-20261010/via_code_overlay_entrypoint.py").read_text()
        self.assertIn('run_name="v5_existing_runtime"',entry)
        self.assertIn('ns.get("mcp")',entry)
        self.assertIn('register(mcp,core)',entry)
        self.assertNotIn("exec(",entry)
    def test_candidate_no_socket_no_external_port_no_secret(self):
        compose=(ROOT/"docker-compose.via-code-candidate.yml").read_text()
        self.assertNotIn("/var/run/docker.sock",compose)
        self.assertNotIn("ROTEIA_API_KEY",compose)
        self.assertNotIn("env_file:",compose)
        self.assertIn('127.0.0.1:18869:8000',compose)
        self.assertIn("read_only: true",compose)
        self.assertIn('["CMD", "python", "/app/via_code_mcp_probe.py"]',compose)
        self.assertIn("no-new-privileges:true",compose)

if __name__=="__main__":
    unittest.main()
