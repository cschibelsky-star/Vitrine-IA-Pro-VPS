import unittest
from asset_host_policy_overlay import apply

class AssetHostGuardTests(unittest.TestCase):
    def test_scoped_grant_preserves_existing_policy(self):
        source = "from typing import Any\nCONTROLLED_COMPOSE_POLICY: dict[str, dict[str, Any]] = {\n    'other': {'up': set()},\n}\n"
        result = apply(source)
        self.assertIn('"asset-host"', result)
        self.assertIn("'other': {'up': set()}", result)
        self.assertIn('"up": {"asset-host"}', result)
    def test_fail_closed_if_no_anchor(self):
        with self.assertRaises(RuntimeError):
            apply("unrelated source")
    def test_fail_closed_on_double_application(self):
        source = "from typing import Any\nCONTROLLED_COMPOSE_POLICY: dict[str, dict[str, Any]] = {\n}\n"
        with self.assertRaises(RuntimeError):
            apply(apply(source))

if __name__ == "__main__":
    unittest.main()
