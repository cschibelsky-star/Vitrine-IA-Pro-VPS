"""Offline safeguards; dependency-free checks."""
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1].joinpath("server.py").read_text()

class SafetyTests(unittest.TestCase):
    def test_paid_disabled_default(self):
        self.assertIn('os.getenv("AVELLO_PAID_ENABLED", "false")', SOURCE)
    def test_bearer_guard(self):
        self.assertIn("hmac.compare_digest", SOURCE)
    def test_provider_is_https(self):
        self.assertIn('https://avellogateway.online/v1/responses', SOURCE)
    def test_no_executor(self):
        self.assertNotIn("subprocess", SOURCE)
        self.assertNotIn("os.system", SOURCE)
    def test_model_allowlist(self):
        for model in ("gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna"):
            self.assertIn(model, SOURCE)
    def test_timeout(self):
        self.assertIn("timeout=65", SOURCE)

if __name__ == "__main__":
    unittest.main()
