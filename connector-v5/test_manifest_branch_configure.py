"""Isolated metadata tests: no Docker, network, or production files."""
import ast
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class BranchConfigureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / 'example.json'
        self.repo = self.root / 'repository'
        (self.repo / '.git').mkdir(parents=True)
        self.data = {'id': 'example', 'repository': {'url': 'https://github.com/example/project.git', 'branch': 'old', 'directory': 'repository'}, 'docker': {'service': 'web'}, 'runtime': {'allowed_keys': []}, 'unknown_field': {'preserve': True}}
        self.manifest.write_text(json.dumps(self.data))
        self.original = self.manifest.read_bytes()
        self.sha = 'a' * 40
        self.audit = Mock()
        self.run = Mock(side_effect=[SimpleNamespace(returncode=0), SimpleNamespace(returncode=0, stdout=self.sha + '\trefs/heads/new\n')])
        source = Path(__file__).with_name('main.py').read_text()
        tree = ast.parse(source)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'project_manifest_branch_configure')
        function.decorator_list = []
        self.ns = {'Any': object, 'Path': Path, 'datetime': datetime, 'timezone': timezone, 'json': json, 'os': os, 'subprocess': SimpleNamespace(run=self.run), '_audit': self.audit, '_safe_project_id': lambda value: value, '_manifest_path': lambda value: self.manifest, '_project_paths': lambda value: (json.loads(self.manifest.read_text()), self.root, self.repo), '_validated_repository_url': lambda value: value}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<isolated-tool>', 'exec'), self.ns)

    def call(self, **overrides):
        args = dict(project_id='example', branch='new', expected_current_branch='old', expected_remote_commit=self.sha, confirm='EXECUTAR')
        args.update(overrides)
        return self.ns['project_manifest_branch_configure'](**args)

    def test_updates_only_branch_and_preserves_exact_backup(self):
        result = self.call()
        self.assertEqual(result['status'], 'configured')
        expected = json.loads(json.dumps(self.data))
        expected['repository']['branch'] = 'new'
        self.assertEqual(json.loads(self.manifest.read_text()), expected)
        backup = self.root / result['backup_name']
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.audit.call_count, 2)
        self.assertEqual([c.args[0][1] for c in self.run.call_args_list], ['check-ref-format', 'ls-remote'])
        self.assertEqual(self.run.call_args_list[1].args[0][4], self.data['repository']['url'])

    def test_confirmation_and_invalid_inputs_never_touch_manifest(self):
        for overrides in ({'confirm': ''}, {'branch': '-bad'}, {'branch': ' new'}, {'expected_remote_commit': 'bad'}, {'expected_current_branch': ''}):
            with self.subTest(overrides=overrides):
                self.assertFalse(self.call(**overrides)['ok'])
                self.assertEqual(self.manifest.read_bytes(), self.original)
        self.run.assert_not_called()

    def test_conflicting_official_branch(self):
        self.assertEqual(self.call(expected_current_branch='stale')['error'], 'official_branch_conflict')
        self.run.assert_not_called()
        self.assertEqual(self.manifest.read_bytes(), self.original)

    def test_remote_commit_mismatch_does_not_write(self):
        self.run.side_effect = [SimpleNamespace(returncode=0), SimpleNamespace(returncode=0, stdout='b' * 40 + '\trefs/heads/new\n')]
        self.assertEqual(self.call()['error'], 'remote_branch_commit_not_verified')
        self.assertEqual(self.manifest.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('*.bak-*')))

    def test_invalid_git_ref(self):
        self.run.side_effect = [SimpleNamespace(returncode=1)]
        self.assertEqual(self.call(branch='bad..ref')['error'], 'invalid_branch')
        self.assertEqual(self.manifest.read_bytes(), self.original)

    def test_audit_failure_before_write_preserves_record(self):
        self.audit.side_effect = OSError('unavailable')
        with self.assertRaises(OSError):
            self.call()
        self.assertEqual(self.manifest.read_bytes(), self.original)
        self.assertEqual(len(list(self.root.glob('*.bak-*'))), 1)

    def test_completion_audit_failure_reports_committed_update(self):
        self.audit.side_effect = [None, OSError('unavailable')]
        result = self.call()
        self.assertTrue(result['ok'])
        self.assertTrue(result['audit_completion_failed'])
        self.assertEqual(json.loads(self.manifest.read_text())['repository']['branch'], 'new')

    def test_idempotent_request(self):
        self.data['repository']['branch'] = 'new'
        self.manifest.write_text(json.dumps(self.data))
        self.assertEqual(self.call(expected_current_branch='new')['status'], 'unchanged')
        self.assertFalse(list(self.root.glob('*.bak-*')))

    def test_intervening_writer_is_not_overwritten(self):
        def intervening(*args):
            self.manifest.write_text('{"changed": true}')
        self.audit.side_effect = intervening
        self.assertEqual(self.call()['error'], 'manifest_changed_before_write')
        self.assertEqual(json.loads(self.manifest.read_text()), {'changed': True})
        self.assertFalse(list(self.root.glob('.branch-*')))


if __name__ == '__main__':
    unittest.main()
