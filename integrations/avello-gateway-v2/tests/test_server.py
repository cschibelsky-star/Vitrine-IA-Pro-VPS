"""Offline unit tests; no external network or paid inference."""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server

class GatewayV2Tests(unittest.TestCase):
    def test_status_has_no_secret(self):
        with patch.dict(os.environ, {"AVELLO_V2_API_KEY": "offline-placeholder"}, clear=True):
            result = server.gateway_status()
        self.assertTrue(result["gateway_key_present"])
        self.assertNotIn("offline-placeholder", str(result))
        self.assertFalse(result["inference_enabled"])

    def test_no_key_never_calls_network(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(server.urllib.request, "build_opener", side_effect=AssertionError("network")):
                self.assertEqual(server.gateway_models()["status"], "not_configured")

    def test_catalog_uses_fixed_get(self):
        opener = Mock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"data":[{"id":"gpt-test"}]}'
        with patch.dict(os.environ, {"AVELLO_V2_API_KEY": "offline-placeholder"}, clear=True):
            with patch.object(server.urllib.request, "build_opener", return_value=opener):
                result = server.gateway_models()
        self.assertEqual(result, {"status": "ok", "models": ["gpt-test"]})
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "https://avellogateway.online/v1/models")
        self.assertEqual(req.get_method(), "GET")

if __name__ == "__main__":
    unittest.main()
