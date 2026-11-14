"""No-network policy tests with temporary SQLite ledger."""
import hashlib
import hmac
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch_authorization as policy


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {
            "VIA_DISPATCH_APPROVAL_HMAC_KEY": "offline-test-secret-32-characters-long",
            "VIA_DISPATCH_NONCE_DB": str(Path(self.tmp.name) / "ledger.sqlite"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.identity = "verified-operator"
        self.nonce = "a" * 32
        self.issued = 1700000000

    def signature(self, identity=None, nonce=None, issued=None):
        return hmac.new(os.environ["VIA_DISPATCH_APPROVAL_HMAC_KEY"].encode(),
                        policy.canonical_message(identity or self.identity, nonce or self.nonce,
                                                 self.issued if issued is None else issued),
                        hashlib.sha256).hexdigest()

    def test_accepts_once_and_rejects_replay(self):
        signature = self.signature()
        result = policy.authorize(self.identity, self.nonce, self.issued, signature, now=self.issued)
        self.assertTrue(result["authorized"])
        with self.assertRaisesRegex(policy.AuthorizationDenied, "audit_unavailable"):
            policy.authorize(self.identity, self.nonce, self.issued, signature, now=self.issued)

    def test_rejects_forged_identity(self):
        with self.assertRaisesRegex(policy.AuthorizationDenied, "invalid_signature"):
            policy.authorize("other-operator", self.nonce, self.issued, self.signature(), now=self.issued)

    def test_rejects_expired(self):
        with self.assertRaisesRegex(policy.AuthorizationDenied, "expired"):
            policy.authorize(self.identity, self.nonce, self.issued, self.signature(), now=self.issued + 121)

    def test_rejects_missing_server_policy(self):
        with patch.dict(os.environ, {"VIA_DISPATCH_APPROVAL_HMAC_KEY": ""}):
            with self.assertRaisesRegex(policy.AuthorizationDenied, "policy_not_configured"):
                policy.authorize(self.identity, self.nonce, self.issued, self.signature(), now=self.issued)

    def test_rejects_invalid_nonce(self):
        with self.assertRaisesRegex(policy.AuthorizationDenied, "invalid_nonce"):
            policy.authorize(self.identity, "oops", self.issued, "0"*64, now=self.issued)


if __name__ == "__main__":
    unittest.main()
