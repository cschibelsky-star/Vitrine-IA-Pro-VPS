"""Offline static boundary checks; these do not call the provider."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.hml.yml").read_text(encoding="utf-8")

class SafetyTests(unittest.TestCase):
    def test_calls_disabled_default(self):
        self.assertIn('os.getenv("AVELLO_CALLS_ENABLED", "false")', BRIDGE)
    def test_auth_guard(self):
        self.assertIn("hmac.compare_digest", SERVER)
        self.assertIn('status_code=401', SERVER)
    def test_gpt_endpoint_https(self):
        self.assertIn("https://avellogateway.online/v1/responses", BRIDGE)
    def test_no_process_executor(self):
        self.assertNotIn("subprocess", SERVER + BRIDGE)
        self.assertNotIn("os.system", SERVER + BRIDGE)
    def test_models(self):
        for m in ("gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna"):
            self.assertIn(m, BRIDGE)
    def test_timeouts(self):
        self.assertIn("timeout=65", BRIDGE)
    def test_local_only_host_port(self):
        self.assertIn("127.0.0.1:18765:8765", COMPOSE)
    def test_no_privileged_container(self):
        self.assertIn("no-new-privileges:true", COMPOSE)
        self.assertIn("read_only: true", COMPOSE)

if __name__ == "__main__":
    unittest.main()
