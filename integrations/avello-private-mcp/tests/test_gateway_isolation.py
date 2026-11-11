"""Offline-only contract checks for Avello gateway; no credentials or network calls."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


class GatewayIsolationTests(unittest.TestCase):
    def setUp(self):
        bridge._CATALOG_CACHE.clear()

    def tearDown(self):
        bridge._CATALOG_CACHE.clear()

    def test_catalog_requires_key_and_makes_no_network_request(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(bridge.urllib.request, "build_opener", side_effect=AssertionError("network forbidden")):
                self.assertEqual(bridge.list_models("gpt")["status"], "not_configured")

    def test_catalog_uses_fixed_https_endpoint_without_redirects(self):
        import io
        opener = Mock()
        opener.open.return_value = io.BytesIO(b'{"data":[{"id":"gpt-test"}]}')
        with patch.dict(os.environ, {"AVELLO_GPT_API_KEY": "offline-placeholder"}, clear=True):
            with patch.object(bridge.urllib.request, "build_opener", return_value=opener) as build:
                result = bridge.list_models("gpt")
        self.assertEqual(result["status"], "ok")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://avellogateway.online/v1/models")
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertTrue(any(isinstance(handler, bridge.urllib.request.HTTPRedirectHandler)
                            for handler in build.call_args.args))
        self.assertNotIn("offline-placeholder", str(result))

    def test_inference_is_disabled_without_explicit_gate(self):
        with patch.dict(os.environ, {"AVELLO_GPT_API_KEY": "offline-placeholder"}, clear=True):
            with patch.object(bridge, "_call", side_effect=AssertionError("inference forbidden")):
                self.assertEqual(bridge.ask("test")["reason"], "calls_disabled")


if __name__ == "__main__":
    unittest.main()
