from pathlib import Path
import tempfile
import unittest
import install_heygen_runtime_inventory as installer


class InstallerTests(unittest.TestCase):
    def fixture(self, root):
        (root/'tvsumare_operations.py').write_text('def auth(): pass\n# LOCAL_EXTENSION\n')
        (root/'tvsumare_tools.py').write_text('def _request(*args, **kwargs): pass\n')
        (root/'main.py').write_text('@mcp.tool()\ndef existing(): pass\n\nif __name__ == "__main__":\n    pass\n')
        (root/'Dockerfile').write_text('FROM python:3.12\nWORKDIR /app\nCOPY main.py ./\n')

    def test_preserves_extensions_backup_registration_and_idempotence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            result = installer.apply(root, Path(__file__).parent)
            self.assertEqual(result['status'], 'installed_not_activated')
            self.assertIn('LOCAL_EXTENSION', (root/'tvsumare_operations.py').read_text())
            self.assertIn('readOnlyHint', (root/'main.py').read_text())
            self.assertIn('COPY heygen_runtime_audit.py', (root/'Dockerfile').read_text())
            self.assertTrue((Path(result['backup'])/'main.py').is_file())
            self.assertEqual(installer.apply(root, Path(__file__).parent)['status'], 'already_installed')

    def test_incompatible_registry_prevents_every_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root/'main.py').write_text('raise RuntimeError()\n')
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            with self.assertRaises(ValueError):
                installer.apply(root, Path(__file__).parent)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
