"""Offline tests; no GitHub calls and no credentials."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import github_actions_dispatch as guard


class DispatchGuardTests(unittest.TestCase):
    def test_reject_other_targets_and_inputs(self):
        for repo, workflow, ref, inputs in [
            ("other/repo", guard.WORKFLOW, guard.BRANCH, None),
            (guard.REPOSITORY, "android-apk.yml", guard.BRANCH, None),
            (guard.REPOSITORY, guard.WORKFLOW, "main", None),
            (guard.REPOSITORY, guard.WORKFLOW, guard.BRANCH, {"publish": "true"}),
        ]:
            with self.assertRaises(guard.DispatchError):
                guard.validate_request(repo, workflow, ref, inputs)

    def test_no_credential_fails_before_network(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(guard.urllib.request, "build_opener", side_effect=AssertionError("network called")):
                with self.assertRaisesRegex(guard.DispatchError, "credential_not_configured"):
                    guard.dispatch(guard.REPOSITORY, guard.WORKFLOW, guard.BRANCH)

    def test_dispatch_fixed_post_and_no_token_in_response(self):
        response = MagicMock()
        response.status = 204
        response.read.return_value = b""
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch.dict(os.environ, {"VIA_GITHUB_ACTIONS_DISPATCH_TOKEN": "TEST_TOKEN_123456789"}, clear=True):
            with patch.object(guard.urllib.request, "build_opener", return_value=opener):
                result = guard.dispatch(guard.REPOSITORY, guard.WORKFLOW, guard.BRANCH)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url,
                         "https://api.github.com/repos/cschibelsky-star/JARVIS/actions/workflows/via-android-118-isolated-validation.yml/dispatches")
        self.assertEqual(json.loads(request.data), {"ref": guard.BRANCH})
        self.assertNotIn("TEST_TOKEN_123456789", str(result))
        self.assertEqual(result["status"], "accepted_not_verified")

    def test_github_failure_is_sanitized(self):
        error = guard.urllib.error.HTTPError("url", 403, "denied", {}, None)
        opener = MagicMock()
        opener.open.side_effect = error
        with patch.dict(os.environ, {"VIA_GITHUB_ACTIONS_DISPATCH_TOKEN": "TEST_TOKEN_123456789"}, clear=True):
            with patch.object(guard.urllib.request, "build_opener", return_value=opener):
                with self.assertRaisesRegex(guard.DispatchError, "github_http_403"):
                    guard.dispatch(guard.REPOSITORY, guard.WORKFLOW, guard.BRANCH)


if __name__ == "__main__":
    unittest.main()
