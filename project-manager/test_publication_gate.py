import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Reuse the minimal optional-dependency shim used by existing tests.
from test_project_manager_operations import ops


class PublicationGateTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'id': 'conheca-sumare-prod', 'environment': 'production',
            'repository': {'url': 'https://github.com/cschibelsky-star/visite-sumare.git', 'branch': 'release'}}
        self.sha = 'a' * 40

    def test_unknown_environment_is_blocked(self):
        manifest = dict(self.manifest, id='unclassified')
        manifest.pop('environment')
        with self.assertRaises(ops.HTTPException):
            ops.publication_preflight(manifest, Path('/absent'), self.sha)

    def test_missing_commit_is_blocked(self):
        with self.assertRaises(ops.HTTPException):
            ops.publication_preflight(self.manifest, Path('/absent'), None)

    def test_no_production_mutation_before_authorization(self):
        with patch.object(ops, 'load_manifest', return_value=self.manifest), \
             patch.object(ops, 'project_paths', return_value=(Path('/absent'), Path('/absent/repo'), Path('/absent/releases'))), \
             patch.object(ops, 'run') as run, \
             patch.object(ops.urllib.request, 'urlopen', side_effect=RuntimeError('blocked')), \
             patch.dict(ops.os.environ, {'PUBLICATION_CONTROL_URL': 'https://control.example', 'PUBLICATION_EXECUTOR_TOKEN': 'x' * 32}):
            with self.assertRaises(ops.HTTPException):
                ops.project_clone(ops.PublicationProjectRequest(project_id='conheca-sumare-prod', target_sha=self.sha))
            run.assert_not_called()

    def test_dirty_tree_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / '.git').mkdir()
            with patch.object(ops, 'run', return_value={'ok': True, 'stdout': ' M Home.jsx'}), \
                 patch.object(ops.urllib.request, 'urlopen') as remote:
                with self.assertRaises(ops.HTTPException):
                    ops.publication_preflight(self.manifest, path, self.sha)
                remote.assert_not_called()

    def test_known_pilot_cannot_claim_homologation(self):
        with self.assertRaises(ops.HTTPException):
            ops.publication_preflight(dict(self.manifest, environment='homologation'), Path('/absent'), None)

    def test_explicit_hml_does_not_consume_production_approval(self):
        with patch.object(ops.urllib.request, 'urlopen') as remote:
            self.assertIsNone(ops.publication_preflight(dict(self.manifest, id='hml', environment='homologation'), Path('/absent'), None))
            remote.assert_not_called()
