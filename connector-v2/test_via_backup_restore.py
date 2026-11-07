import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import via_backup_restore as mod

class ViaBackupRestoreTests(unittest.TestCase):
    def test_rejects_invalid_backup_name(self):
        with self.assertRaises(ValueError):
            mod.verify_via_backup("../other.tar.gz", "a" * 64)

    def test_checksum_and_via_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "vps-filesystem-test.tar.gz"
            archive = root / name
            with tarfile.open(archive, "w:gz") as tar:
                data = b"example"
                member = tarfile.TarInfo("srv/projects/via/data/example.txt")
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
            sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(mod, "BACKUP_ROOT", root), patch.object(mod, "RESTORE_ROOT", root / "isolated"):
                self.assertEqual(mod.verify_via_backup(name, sha)["via_members"], 1)
                with self.assertRaises(ValueError):
                    mod.verify_via_backup(name, "0" * 64)
                (root / "isolated").mkdir()
                result = mod.verify_via_backup(name, sha, restore=True)
                self.assertTrue(result["restored"])
                self.assertEqual((root / "isolated" / sha[:20] / "data/example.txt").read_bytes(), b"example")

if __name__ == "__main__":
    unittest.main()
