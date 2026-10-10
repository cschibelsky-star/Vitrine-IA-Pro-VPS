"""Real Git and HTTP regression tests, using temporary repositories only."""
import copy
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_project_manager_operations import ops


class CanonicalSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = ops.load_publication_sources()['conheca-sumare']
        self.sha = self.source.get('candidate_sha', self.source['baseline_sha'])
        self.hml = {'id': 'conheca-sumare-origin-hml', 'environment': 'homologation',
            'workspace_root': '/srv/projects/conheca-sumare-origin-hml',
            'repository': {'url': self.source['repository_url'], 'branch': 'moving-template'},
            'docker': {'compose_file': 'docker-compose.origin-hml.yml'}}
        self.prod = dict(self.hml, id='conheca-sumare', environment='production')

    def assert_blocked(self, manifest, sha, detail):
        with patch.object(ops, 'run') as run, patch.object(ops.urllib.request, 'urlopen') as remote:
            with self.assertRaises(ops.HTTPException) as error:
                ops.publication_preflight(manifest, Path('/absent/repository'), sha)
            self.assertEqual(error.exception.detail, detail)
            run.assert_not_called()
            remote.assert_not_called()

    def test_legacy_registry_repository_is_rejected(self):
        manifest = copy.deepcopy(self.prod)
        manifest['repository']['url'] = 'https://github.com/cschibelsky-star/visite-sumare.git'
        self.assert_blocked(manifest, self.sha, 'canonical_repository_mismatch')

    def test_old_template_sha_is_rejected_even_with_cockpit_available(self):
        self.assert_blocked(self.prod, '62d780462572fdeb898887eef0defc2eaef647e4', 'canonical_candidate_sha_mismatch')

    def test_real_production_is_disabled_until_reconciliation(self):
        self.assert_blocked(self.prod, self.sha, 'canonical_production_reconciliation_pending')

    def test_php_production_alias_cannot_claim_hml(self):
        self.assert_blocked(dict(self.prod, environment='homologation'), self.sha, 'production_runtime_cannot_claim_homologation')

    def test_renamed_production_root_cannot_claim_hml(self):
        for name in self.source['production_root_names']:
            root = '/srv/projects/' + name
            self.assert_blocked(dict(self.hml, id='renamed', workspace_root=root + '/nested'), self.sha,
                'production_runtime_cannot_claim_homologation')

    def test_public_domain_cannot_claim_hml(self):
        self.assert_blocked(dict(self.hml, domains={'production': ['conhecasumare.com.br']}), self.sha,
            'production_runtime_cannot_claim_homologation')

    def test_original_public_compose_is_not_an_isolated_candidate(self):
        self.assert_blocked(dict(self.hml, docker={'compose_file': 'docker-compose.hml.yml'}), self.sha,
            'canonical_isolated_compose_required')

    def test_git_worktree_file_is_checked_for_dirty_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / '.git').write_text('gitdir: /unused')
            with patch.object(ops, 'run', return_value={'ok': True, 'stdout': ' M index.php'}) as run:
                with self.assertRaises(ops.HTTPException) as error:
                    ops.publication_preflight(self.hml, repo, self.sha)
                self.assertEqual(error.exception.detail, 'preserve_dirty_repository_before_publication')
                run.assert_called_once()

    def test_wrong_origin_is_not_rewritten_or_fetched(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / '.git').mkdir()
            with patch.object(ops, 'run', side_effect=[{'ok': True, 'stdout': ''},
                {'ok': True, 'stdout': 'https://github.com/cschibelsky-star/visite-sumare.git'}]) as run:
                with self.assertRaises(ops.HTTPException) as error:
                    ops.publication_preflight(self.hml, repo, self.sha)
                self.assertEqual(error.exception.detail, 'canonical_origin_mismatch')
                self.assertEqual(len(run.call_args_list), 2)

    def test_http_endpoint_denies_real_production_without_mutating_checkout(self):
        app = FastAPI()
        app.include_router(ops.router)
        with tempfile.TemporaryDirectory() as directory, patch.object(ops, 'BROKER_TOKEN', 'test-only-token'), \
            patch.object(ops, 'load_manifest', return_value=self.prod), \
            patch.object(ops, 'project_paths', return_value=(Path(directory), Path(directory)/'repo', Path(directory)/'releases')), \
            patch.object(ops, 'run') as run, \
            patch.dict(os.environ, {'PUBLICATION_LOCK_DIRECTORY': directory + '/locks'}):
            response = TestClient(app).post('/projects/clone', json={'project_id': 'conheca-sumare', 'target_sha': self.sha},
                headers={'Authorization': 'Bearer test-only-token'})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['detail'], 'canonical_production_reconciliation_pending')
            self.assertFalse((Path(directory)/'repo').exists())
            run.assert_not_called()

    def test_registry_aliases_share_repository_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(ops, 'load_manifest', side_effect=[self.prod, dict(self.prod, id='conheca-sumare-prod')]), \
                patch.object(ops, 'project_paths', return_value=(root, root/'repository', root/'releases')), \
                patch.object(ops, 'project_clone_locked', return_value={'ok': False}), \
                patch.object(ops, 'publication_lock', return_value=nullcontext()) as lock:
                for project_id in ['conheca-sumare', 'conheca-sumare-prod']:
                    ops.project_clone(ops.PublicationProjectRequest(project_id=project_id, target_sha=self.sha))
                self.assertEqual(lock.call_args_list[0].args, lock.call_args_list[1].args)

    def test_installer_packages_policy_without_modifying_active_connector(self):
        path = Path(__file__).with_name('install_project_manager.py')
        spec = importlib.util.spec_from_file_location('isolated_installer', path)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'ops_broker.py').write_text('from tvsumare_migration_operations import router as tvsumare_migration_router\napp.include_router(tvsumare_migration_router)\n')
            (root/'main.py').write_text('from tvsumare_migration_tools import (\n dummy,\n)\nif __name__ == "__main__":\n pass\n')
            (root/'Dockerfile').write_text('FROM python:3.12-slim\nCOPY main.py ./\n')
            (root/'docker-compose.connector-v2.override.yml').write_text('services:\n  ops_broker:\n    image: isolated\n  vps_mcp_connector:\n    image: isolated\n')
            with patch.object(installer, 'ROOT', root):
                installer.main()
            self.assertEqual(json.loads((root/'publication_sources.json').read_text()), ops.load_publication_sources())
            self.assertIn('publication_sources.json', (root/'Dockerfile').read_text())
            self.assertIn('target_sha', (root/'main.py').read_text())

    def test_real_git_ignores_old_branch_and_preserves_dirty_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root/'upstream'
            upstream.mkdir()
            def git(*args, cwd=upstream):
                return subprocess.check_output(['git', *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
            git('init', '-b', 'moving-template')
            git('config', 'user.name', 'Isolated Test')
            git('config', 'user.email', 'isolated@example.invalid')
            (upstream/'index.php').write_text('OLD TEMPLATE')
            git('add', '.')
            git('commit', '-m', 'old template')
            old = git('rev-parse', 'HEAD')
            (upstream/'index.php').write_text('APPROVED HOMEPAGE')
            git('commit', '-am', 'approved homepage')
            approved = git('rev-parse', 'HEAD')
            git('branch', 'approved', approved)
            git('checkout', '--detach', old)
            git('branch', '-f', 'moving-template', old)
            config = root/'gitconfig'
            config.write_text('')
            fixture = copy.deepcopy(self.source)
            fixture['candidate_sha'] = approved
            fixture['repository_url'] = upstream.as_uri()
            target = root/'runtime'/'repository'
            manifest = copy.deepcopy(self.hml)
            manifest['workspace_root'] = str(target.parent)
            manifest['repository']['url'] = fixture['repository_url']
            commands = []
            real_run = ops.run
            def capture(command, cwd, **kwargs):
                commands.append(command)
                return real_run(command, cwd, **kwargs)
            with patch.object(ops, 'load_publication_sources', return_value={'conheca-sumare': fixture}), \
                patch.object(ops, 'load_manifest', return_value=manifest), \
                patch.object(ops, 'project_paths', return_value=(target.parent, target, root/'releases')), \
                patch.object(ops, 'audit'), patch.object(ops, 'run', side_effect=capture), \
                patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_NOSYSTEM': '1',
                    'PUBLICATION_LOCK_DIRECTORY': str(root/'locks')}):
                request = ops.PublicationProjectRequest(project_id=manifest['id'], target_sha=approved)
                result = ops.project_clone(request)
                self.assertTrue(result['ok'])
                self.assertEqual((target/'index.php').read_text(), 'APPROVED HOMEPAGE')
                self.assertEqual(git('rev-parse', 'HEAD', cwd=target), approved)
                self.assertTrue(ops.project_clone(request)['ok'])
                self.assertFalse(any('pull' in command or '--all' in command or '--prune' in command for command in commands))
                (target/'index.php').write_text('LOCAL WORK MUST SURVIVE')
                with self.assertRaises(ops.HTTPException):
                    ops.project_clone(request)
                self.assertEqual((target/'index.php').read_text(), 'LOCAL WORK MUST SURVIVE')
                self.assertEqual(git('rev-parse', 'HEAD', cwd=target), approved)


if __name__ == '__main__':
    unittest.main()
