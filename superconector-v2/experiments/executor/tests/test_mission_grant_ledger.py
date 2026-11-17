"""Offline deterministic unit tests for persistent one-time HML grant ledger."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mission_grant_ledger import SCHEMA, consume_grant, GrantRejected, LedgerUnavailable

SHA = "a" * 40
NOW = 2000000000

class GrantLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "ledger.sqlite")
        with sqlite3.connect(self.path) as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT INTO approved_missions VALUES (?,?,?,?,?,?,?,?)",
                         ("mission-1","approval-1","tenant-hml","supervisor-1","probe",SHA,NOW+600,None))
        self.claims = dict(jti="grant-1", mission_id="mission-1", approval_id="approval-1",
                           tenant_id="tenant-hml", sub="supervisor-1", approved_profile="probe",
                           source_sha=SHA, exp=NOW+120)

    def tearDown(self):
        self.tmp.cleanup()

    def consume(self, claims=None, path=None):
        consume_grant(self.path if path is None else path,
                      self.claims if claims is None else claims, pinned_sha=SHA, now=NOW)

    def test_approved_once(self):
        self.consume()
        with self.assertRaisesRegex(GrantRejected, "grant_replayed"):
            self.consume()

    def test_replay_after_reopening_db(self):
        self.consume()
        with self.assertRaises(GrantRejected):
            self.consume()

    def test_parallel_same_jti_allows_exactly_one(self):
        def attempt(_):
            try:
                self.consume()
                return True
            except GrantRejected:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 7)

    def test_revoked_approval_denied(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE approved_missions SET revoked_at=? WHERE mission_id=?",
                         (NOW-1, "mission-1"))
        with self.assertRaisesRegex(GrantRejected, "approval_revoked"):
            self.consume()

    def test_expired_approval_denied(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE approved_missions SET expires_at=? WHERE mission_id=?",
                         (NOW-1, "mission-1"))
        with self.assertRaisesRegex(GrantRejected, "approval_revoked"):
            self.consume()

    def test_expired_token_denied(self):
        with self.assertRaisesRegex(GrantRejected, "expired_grant"):
            self.consume({**self.claims, "exp": NOW})

    def test_wrong_tenant_denied(self):
        with self.assertRaisesRegex(GrantRejected, "approval_binding"):
            self.consume({**self.claims, "tenant_id": "another-tenant"})

    def test_wrong_subject_denied(self):
        with self.assertRaises(GrantRejected):
            self.consume({**self.claims, "sub": "another-user"})

    def test_wrong_profile_denied(self):
        with self.assertRaisesRegex(GrantRejected, "approval_binding"):
            self.consume({**self.claims, "approved_profile": "syntax"})

    def test_wrong_sha_denied(self):
        with self.assertRaisesRegex(GrantRejected, "source_sha"):
            self.consume({**self.claims, "source_sha": "b"*40})

    def test_absent_approval_denied(self):
        with self.assertRaisesRegex(GrantRejected, "approval_not_found"):
            self.consume({**self.claims, "approval_id": "unknown"})

    def test_missing_ledger_denied(self):
        with self.assertRaises(LedgerUnavailable):
            self.consume(path=str(Path(self.tmp.name) / "missing.sqlite"))

    def test_missing_tables_denied(self):
        p = str(Path(self.tmp.name) / "empty.sqlite")
        sqlite3.connect(p).close()
        with self.assertRaises(LedgerUnavailable):
            self.consume(path=p)

    def test_empty_path_denied(self):
        with self.assertRaises(LedgerUnavailable):
            self.consume(path="")

    def test_symlink_denied(self):
        p = Path(self.tmp.name) / "link.sqlite"
        p.symlink_to(self.path)
        with self.assertRaises(LedgerUnavailable):
            self.consume(path=str(p))

    def test_denial_does_not_consume_jti(self):
        with self.assertRaises(GrantRejected):
            self.consume({**self.claims, "tenant_id": "other"})
        self.consume()

if __name__ == "__main__":
    unittest.main()
