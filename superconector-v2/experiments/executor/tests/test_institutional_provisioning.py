"""Offline tests for institutionally signed, one-shot approval provisioning."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mission_grant_ledger import SCHEMA, consume_grant, GrantRejected
from institutional_provisioning import apply_signed_approval, ProvisioningDenied

NOW = 2000000000
SHA = "a" * 40

class InstitutionalProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "ledger.sqlite")
        with sqlite3.connect(self.path) as con:
            con.executescript(SCHEMA)
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.data = dict(operation="approve", project_id="super-v2-hml",
                         tenant_id="tenant-hml", mission_id="mission-1",
                         approval_id="approval-1", subject="supervisor-1",
                         profile="probe", source_sha=SHA,
                         expires_at=NOW + 600, issued_at=NOW, nonce="nonce-1")

    def send(self, **overrides):
        item = {**self.data, **overrides}
        raw = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
        return apply_signed_approval(
            db_path=self.path, raw_payload=raw, signature=self.key.sign(raw),
            trusted_public_key=self.pub, expected_project="super-v2-hml",
            expected_tenant="tenant-hml", pinned_sha=SHA, now=NOW)

    def test_approval_then_consume(self):
        self.assertEqual(self.send(), "approve")
        consume_grant(self.path, dict(
            jti="grant-1", mission_id="mission-1", approval_id="approval-1",
            tenant_id="tenant-hml", sub="supervisor-1",
            approved_profile="probe", source_sha=SHA, exp=NOW + 100),
            pinned_sha=SHA, now=NOW)

    def test_duplicate_nonce_rejected(self):
        self.send()
        with self.assertRaisesRegex(ProvisioningDenied, "provisioning_replayed"):
            self.send()

    def test_revocation(self):
        self.send()
        self.assertEqual(self.send(operation="revoke", nonce="nonce-2"), "revoke")
        with sqlite3.connect(self.path) as con:
            self.assertIsNotNone(con.execute(
                "SELECT revoked_at FROM approved_missions").fetchone()[0])

    def test_cross_tenant_rejected(self):
        with self.assertRaises(ProvisioningDenied):
            self.send(tenant_id="other")

    def test_stale_rejected(self):
        with self.assertRaises(ProvisioningDenied):
            self.send(issued_at=NOW-1000)

    def test_bad_signature_rejected(self):
        raw = json.dumps(self.data).encode()
        with self.assertRaisesRegex(ProvisioningDenied, "invalid_signature"):
            apply_signed_approval(
                db_path=self.path, raw_payload=raw, signature=b"0"*64,
                trusted_public_key=self.pub, expected_project="super-v2-hml",
                expected_tenant="tenant-hml", pinned_sha=SHA, now=NOW)

    def test_unknown_revoke_rejected(self):
        with self.assertRaisesRegex(ProvisioningDenied, "approval_not_revocable"):
            self.send(operation="revoke")

    def test_reapproval_same_mission_rejected(self):
        self.send()
        with self.assertRaisesRegex(ProvisioningDenied, "approval_already_exists"):
            self.send(nonce="nonce-2")

if __name__ == "__main__":
    unittest.main()
