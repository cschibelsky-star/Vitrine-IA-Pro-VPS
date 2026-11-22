"""Offline contract tests for the isolated GitHub App token provider."""
import base64
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import github_app_auth as auth


class FakeResponse:
    status = 201
    def __init__(self, data):
        self.data = data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size):
        return json.dumps(self.data).encode()


class FakeOpener:
    def __init__(self, data):
        self.data = data
        self.request = None
    def open(self, request, timeout):
        self.request = request
        return FakeResponse(self.data)


class AppAuthTests(unittest.TestCase):
    def test_invalid_app_id_rejected_before_signing(self):
        with self.assertRaisesRegex(auth.AppAuthError, "invalid_app_id"):
            auth.make_app_jwt("not-an-id", b"key")

    def test_invalid_installation_id_rejected_before_signing(self):
        with self.assertRaisesRegex(auth.AppAuthError, "invalid_installation_id"):
            auth.installation_token("4739135", "oops", b"key")

    def test_missing_private_key_fails_closed(self):
        with patch.dict("os.environ", {"VIA_GITHUB_APP_PRIVATE_KEY_PEM": ""}):
            with self.assertRaisesRegex(auth.AppAuthError, "private_key_not_configured"):
                auth.token_from_server_environment()

    def test_jwt_and_scoped_token_request(self):
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            self.skipTest("cryptography dependency not installed")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        opener = FakeOpener({"token": "ghs_validtoken123456",
                             "permissions": {"actions": "write", "contents": "read"}})
        token = auth.installation_token("4739135", "143831588", pem, opener=opener, now=1700000000)
        self.assertEqual(token, "ghs_validtoken123456")
        self.assertEqual(opener.request.full_url,
                         "https://api.github.com/app/installations/143831588/access_tokens")
        self.assertEqual(json.loads(opener.request.data), {
            "repositories": ["JARVIS"],
            "permissions": {"actions": "write", "contents": "read"}})
        jwt = opener.request.get_header("Authorization").split(" ", 1)[1]
        encoded = jwt.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        self.assertEqual(payload["iss"], "4739135")
        self.assertEqual(payload["iat"], 1699999940)
        self.assertEqual(payload["exp"], 1700000540)

    def test_actions_read_only_response_rejected(self):
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            self.skipTest("cryptography dependency not installed")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        opener = FakeOpener({"token": "ghs_validtoken123456",
                             "permissions": {"actions": "read"}})
        with self.assertRaisesRegex(auth.AppAuthError, "actions_write_not_granted"):
            auth.installation_token("4739135", "143831588", pem, opener=opener)


if __name__ == "__main__":
    unittest.main()
