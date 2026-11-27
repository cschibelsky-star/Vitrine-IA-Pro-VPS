import hashlib
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import assessor_snapshot as snapshot
import maintenance_broker as broker
import maintenance_client as client


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = root / "repository"
        self.dest = root / "private"
        self.dest.mkdir(mode=0o700)
        self.enterContext(patch.object(snapshot, "ROOT", self.source))
        self.enterContext(patch.object(snapshot, "DESTINATION", self.dest))
        for name in snapshot.FILES:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        (self.source / ".env").write_text("not in archive")

    def test_archive_is_private_and_recovers_only_the_fixed_files(self):
        result = broker.operation({"operation": "assessor_hml_snapshot"})
        artifact = self.dest / result["archive"]
        self.assertTrue(result["verified"])
        self.assertEqual(result["sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
        self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
        with tarfile.open(artifact) as archive:
            self.assertEqual(archive.getnames(), list(snapshot.FILES))
            for name in snapshot.FILES:
                self.assertEqual(archive.extractfile(name).read(), (self.source / name).read_bytes())

    def test_symlink_is_rejected_without_publishing(self):
        path = self.source / snapshot.FILES[0]
        path.unlink()
        path.symlink_to(self.source / ".env")
        with self.assertRaises(OSError):
            snapshot.create_snapshot()
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_directory_symlink_is_rejected(self):
        path = self.source / "routes"
        path.rename(self.source / "other")
        path.symlink_to(self.source / "other", target_is_directory=True)
        with self.assertRaises(OSError):
            snapshot.create_snapshot()

    def test_request_cannot_supply_a_destination(self):
        with self.assertRaises(ValueError):
            broker.operation({"operation": "assessor_hml_snapshot", "target": "/tmp"})

    def test_write_scope_and_confirmation(self):
        token = SimpleNamespace(subject="operator", scopes=["projects:read"])
        op = "assessor_hml_snapshot"
        with self.assertRaises(PermissionError):
            client.authorize(token, op, "operator", True, "EXECUTAR")
        token.scopes.append("projects:write")
        with self.assertRaises(PermissionError):
            client.authorize(token, op, "operator", True)
        client.authorize(token, op, "operator", True, "EXECUTAR")
