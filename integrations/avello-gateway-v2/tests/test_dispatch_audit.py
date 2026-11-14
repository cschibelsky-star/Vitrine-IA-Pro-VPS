"""Offline persistent dispatch audit tests."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dispatch_audit import record, AuditUnavailable


class AuditTests(unittest.TestCase):
    def test_persists_sanitized_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "ledger.sqlite")
            with patch.dict(os.environ, {"VIA_DISPATCH_NONCE_DB": path}):
                record("operator-1", "a"*32, "blocked", "dispatch_attempt")
                record("operator-1", "a"*32, "accepted_not_verified")
            with sqlite3.connect(path) as db:
                rows = db.execute("SELECT identity, nonce, outcome FROM dispatch_events ORDER BY event_id").fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1][2], "accepted_not_verified")

    def test_missing_audit_storage_fails_closed(self):
        with patch.dict(os.environ, {"VIA_DISPATCH_NONCE_DB": ""}):
            with self.assertRaisesRegex(AuditUnavailable, "audit_not_configured"):
                record("operator-1", "a"*32, "blocked")

    def test_invalid_outcome_is_rejected(self):
        with self.assertRaisesRegex(AuditUnavailable, "invalid_outcome"):
            record("operator-1", "a"*32, "published")


if __name__ == "__main__":
    unittest.main()
