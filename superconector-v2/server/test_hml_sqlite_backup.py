import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import hml_sqlite_backup as backup
import maintenance_broker as broker
import maintenance_client as client


class SQLiteBackupTests(unittest.TestCase):
    def setUp(self):
        temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.volume = temp / "volume"
        self.volume.mkdir()
        self.dest = temp / "private"
        self.dest.mkdir(mode=0o700)
        self.enterContext(patch.object(backup, "VOLUME_DIR", self.volume))
        self.enterContext(patch.object(backup, "DESTINATION", self.dest))
        self.source = self.volume / "assessor.sqlite"
        self.mount = {"Type": "volume", "Name": backup.VOLUME, "Source": str(self.volume),
                      "Driver": "local", "Destination": backup.STORAGE}

    def inspect(self, project=backup.COMPOSE_PROJECT):
        state = f'{"a"*64}|{project}|{backup.SERVICE}|running|{json.dumps([self.mount])}'
        return Mock(return_value=state)

    def test_backup_includes_committed_wal_data(self):
        with closing(sqlite3.connect(self.source)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE sample(value TEXT)")
            writer.execute("INSERT INTO sample VALUES ('committed')")
            writer.commit()
            writer.execute("INSERT INTO sample VALUES ('uncommitted')")
            self.assertTrue(self.source.with_name("assessor.sqlite-wal").exists())
            docker = self.inspect()
            result = backup.create_backup(docker)
        artifact = self.dest / result["archive"]
        self.assertTrue(result["verified"])
        self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), result["sha256"])
        with closing(sqlite3.connect(artifact)) as restored:
            self.assertEqual(restored.execute("SELECT value FROM sample").fetchall(), [("committed",)])
        self.assertEqual(docker.call_args.args[-1], backup.CONTAINER)

    def test_rejects_wrong_project_volume_and_symbolic_source(self):
        with self.assertRaises(PermissionError):
            backup.create_backup(self.inspect("production"))
        self.mount["Name"] = "other-volume"
        with self.assertRaises(PermissionError):
            backup.create_backup(self.inspect())
        self.mount["Name"] = backup.VOLUME
        self.source.symlink_to(self.dest)
        with self.assertRaises(PermissionError):
            backup.create_backup(self.inspect())
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_corrupt_database_cannot_publish_partial_copy(self):
        self.source.write_bytes(b"not sqlite")
        with self.assertRaises(sqlite3.DatabaseError):
            backup.create_backup(self.inspect())
        self.assertEqual(list(self.dest.iterdir()), [])

    @patch.object(broker.hml_sqlite_backup, "create_backup")
    def test_broker_scope_and_project_allowlist(self, create):
        operation = "project_hml_database_backup"
        with self.assertRaises(PermissionError):
            broker.operation({"operation": operation, "project_id": "cockpit-admin-v1-hml"})
        with self.assertRaises(ValueError):
            broker.operation({"operation": operation, "project_id": backup.PROJECT_ID, "path": "/tmp"})
        create.assert_not_called()
        token = SimpleNamespace(subject="operator", scopes=["projects:read", "projects:write"])
        with self.assertRaises(PermissionError):
            client.authorize(token, operation, "operator", True)
        client.authorize(token, operation, "operator", True, "EXECUTAR")
