import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime_publication_guard as guard
from install_runtime_publication_guard import broker_overlay, independent_overlay


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'publication_sources.json').write_text(json.dumps({'conheca-sumare': {
            'production_enabled': False, 'production_project_ids': ['conheca-sumare', 'conheca-sumare-prod'],
            'homologation_project_ids': ['conheca-sumare-origin-hml'],
            'production_root_names': ['conheca-sumare', 'conheca-sumare-prod'],
            'production_hosts': ['conhecasumare.com.br']}}))
        self.p = patch.object(guard, '__file__', str(self.root / 'runtime_publication_guard.py'))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_ids_paths_domains_aliases_and_hml_blocked(self):
        cases = [('conheca-sumare', {}), ('conheca-sumare-origin-hml', {}),
                 ('alias', {'workspace_root': '/tmp/conheca-sumare'}),
                 ('alias', {'workspace': {'root': '/tmp/conheca-sumare-prod'}}),
                 ('alias', {'workspace_root': '/tmp/alias', 'repository': {'directory': '../conheca-sumare-prod'}}),
                 ('alias', {'domains': {'production': ['conhecasumare.com.br']}})]
        for project_id, manifest in cases:
            with self.subTest(project_id=project_id, manifest=manifest):
                self.assertEqual(guard.preflight(project_id, lambda _: manifest)['error'], 'canonical_production_reconciliation_pending')

    def test_read_only_and_unrelated_operations(self):
        self.assertIsNone(guard.preflight('conheca-sumare', None, operation='status'))
        self.assertIsNone(guard.preflight('other', lambda _: {'workspace_root': '/tmp/other'}))

    def test_missing_policy_blocks(self):
        (self.root / 'publication_sources.json').unlink()
        self.assertEqual(guard.preflight('other', lambda _: {})['error'], 'canonical_source_policy_unavailable')

    def test_bootstrap_blocks_before_loader_and_execution(self):
        source = 'def project_bootstrap_from_git(project_id, workspace_root):\n    calls.append(project_id)\n    return True\n'
        transformed, names = independent_overlay(source, 'loader')
        scope = {'calls': [], 'loader': lambda _: (_ for _ in ()).throw(RuntimeError())}
        exec(transformed, scope)
        result = scope['project_bootstrap_from_git']('alias', '/tmp/conheca-sumare')
        self.assertFalse(result['ok'])
        self.assertEqual(scope['calls'], [])
        self.assertEqual(names, ['project_bootstrap_from_git'])

    def test_decorated_executor_keeps_signature_and_existing_extensions(self):
        source = '@register\ndef project_clone(project_id):\n    calls.append(project_id)\n    return True\n\ndef extension():\n    return 7\n'
        transformed, _ = independent_overlay(source, 'loader')
        scope = {'calls': [], 'register': lambda fn: fn, 'loader': lambda _: {}}
        exec(transformed, scope)
        self.assertFalse(scope['project_clone']('conheca-sumare')['ok'])
        self.assertEqual(scope['calls'], [])
        self.assertEqual(scope['extension'](), 7)

    def test_broker_overlay_preserves_unrelated_endpoints(self):
        current = 'from __future__ import annotations\nclass ProjectRequest: pass\ndef project_clone(req):\n    return "old"\ndef project_write_file():\n    return "extension"\n'
        reviewed = 'class PublicationProjectRequest(ProjectRequest): pass\ndef project_clone(req):\n    return "guarded"\ndef project_clone_locked(req, manifest):\n    return "locked"\n'
        result = broker_overlay(current, reviewed)
        scope = {}
        exec(result, scope)
        self.assertEqual(scope['project_clone'](None), 'guarded')
        self.assertEqual(scope['project_write_file'](), 'extension')
        self.assertNotIn('return "old"', result)


if __name__ == '__main__':
    unittest.main()
