"""Isolated cryptographic tests, with generated ephemeral keys and no network."""
from datetime import datetime, timezone
import pathlib
import sys
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mission_grant_issuer import ApprovedMission, GrantDenied, issue_mission_grant

SHA = "a" * 40
NOW = datetime(2026, 11, 17, 20, 0, tzinfo=timezone.utc)


class MissionGrantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        cls.public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def setUp(self):
        self.mission = ApprovedMission("mission-1", "approval-1", "tenant-hml", "probe", SHA, "supervisor-1")

    def issue(self, **changes):
        args = dict(authenticated_subject="supervisor-1", mission=self.mission,
                    lookup_approval=lambda mission_id, approval_id: self.mission,
                    private_key_pem=self.private, issuer="https://auth.example.invalid/hml",
                    audience="super-private-executor-hml", expected_tenant="tenant-hml",
                    pinned_source_sha=SHA, now=NOW)
        args.update(changes)
        return issue_mission_grant(**args)

    def test_signed_grant_matches_executor_contract(self):
        token = self.issue()
        claims = jwt.decode(token, self.public, algorithms=["RS256"], audience="super-private-executor-hml", issuer="https://auth.example.invalid/hml", options={"verify_exp": False, "verify_nbf": False})
        self.assertEqual(claims["approved_profile"], "probe")
        self.assertEqual(claims["scope"], "executor:hml:run")
        self.assertEqual(claims["exp"] - claims["iat"], 120)
        self.assertEqual(claims["source_sha"], SHA)

    def test_wrong_subject_fails(self):
        with self.assertRaises(GrantDenied):
            self.issue(authenticated_subject="other-user")

    def test_unknown_approval_fails(self):
        with self.assertRaises(GrantDenied):
            self.issue(lookup_approval=lambda *_: None)

    def test_mismatched_record_fails(self):
        with self.assertRaises(GrantDenied):
            self.issue(lookup_approval=lambda *_: ApprovedMission("mission-1", "approval-2", "tenant-hml", "probe", SHA, "supervisor-1"))

    def test_cross_tenant_fails(self):
        with self.assertRaises(GrantDenied):
            self.issue(expected_tenant="other-tenant")

    def test_unpinned_sha_fails(self):
        with self.assertRaises(GrantDenied):
            self.issue(pinned_source_sha="b" * 40)

    def test_unapproved_profile_fails(self):
        bad = ApprovedMission("mission-1", "approval-1", "tenant-hml", "shell", SHA, "supervisor-1")
        with self.assertRaises(GrantDenied):
            self.issue(mission=bad, lookup_approval=lambda *_: bad)

    def test_grant_lifetime_limit(self):
        with self.assertRaises(GrantDenied):
            self.issue(ttl_seconds=301)

    def test_no_issuer_key_fails(self):
        with self.assertRaises(GrantDenied):
            self.issue(private_key_pem="")

    def test_signature_cannot_be_validated_by_unrelated_key(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_public = other.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaises(jwt.InvalidSignatureError):
            jwt.decode(self.issue(), other_public, algorithms=["RS256"], audience="super-private-executor-hml", issuer="https://auth.example.invalid/hml", options={"verify_exp": False, "verify_nbf": False})


if __name__ == "__main__":
    unittest.main()
