"""Offline tests for the allowlisted Super GitHub Actions dispatcher."""
import os
import unittest
from unittest.mock import patch, MagicMock
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
import sys
import types

class DummyMCP:
    def __init__(self, *args, **kwargs): pass
    def tool(self, *args, **kwargs): return lambda fn: fn

sys.modules.setdefault("fastmcp", types.SimpleNamespace(FastMCP=DummyMCP))
sys.modules.setdefault("psutil", types.SimpleNamespace())
spec = spec_from_file_location("super_main_dispatch_test", Path(__file__).resolve().parents[1] / "main.py")
module = module_from_spec(spec)
spec.loader.exec_module(module)

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.repo = "cschibelsky-star/Vitrine-IA-Pro-VPS"
        self.workflow = "avello-gateway-v2-isolated.yml"
        self.ref = "feature/avello-gateway-v2-isolated-20261111"

    @patch.object(module, "_audit")
    @patch("urllib.request.urlopen")
    def test_confirmation_required_no_network(self, request, audit):
        result = module.github_actions_dispatch(self.repo, self.workflow, self.ref)
        self.assertEqual(result["error"], "confirmation_required")
        request.assert_not_called()

    @patch.object(module, "_audit")
    @patch("urllib.request.urlopen")
    def test_disallowed_workflow_no_network(self, request, audit):
        result = module.github_actions_dispatch(self.repo, "deploy-super-hml.yml", self.ref, "EXECUTAR")
        self.assertEqual(result["error"], "workflow_or_ref_not_allowlisted")
        request.assert_not_called()

    @patch.object(module, "_audit")
    @patch("urllib.request.urlopen")
    def test_disallowed_branch_no_network(self, request, audit):
        result = module.github_actions_dispatch(self.repo, self.workflow, "main", "EXECUTAR")
        self.assertEqual(result["error"], "workflow_or_ref_not_allowlisted")
        request.assert_not_called()

    @patch.object(module, "_audit")
    @patch("urllib.request.urlopen")
    def test_missing_token_no_network(self, request, audit):
        with patch.dict(os.environ, {}, clear=True):
            result = module.github_actions_dispatch(self.repo, self.workflow, self.ref, "EXECUTAR")
        self.assertEqual(result["error"], "github_actions_token_not_configured")
        request.assert_not_called()

    @patch.object(module, "_audit")
    @patch("urllib.request.urlopen")
    def test_dispatch_204(self, request, audit):
        response = MagicMock()
        response.__enter__.return_value.status = 204
        request.return_value = response
        with patch.dict(os.environ, {"SUPER_GITHUB_ACTIONS_TOKEN": "fake-test-token"}):
            result = module.github_actions_dispatch(self.repo, self.workflow, self.ref, "EXECUTAR")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 204)
        req = request.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertIn(b'"ref"', req.data)
        self.assertNotIn("fake-test-token", str(result))
        self.assertNotIn("fake-test-token", str(audit.call_args))

if __name__ == "__main__":
    unittest.main()
