"""Scoped regression checks; does not execute Docker or import the MCP host."""
import ast
from pathlib import Path
from typing import Any
import unittest

PROJECT = 'factory-asset-intake-validation-20261015'
SERVICE = 'asset-validation'
COMPOSE = 'docker-compose.asset-validation.yml'

class FactoryAssetPolicyTests(unittest.TestCase):
    def setUp(self):
        module = ast.parse(Path(__file__).with_name('controlled_operations_patch.py').read_text())
        literal = next(n.value for n in ast.walk(module) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'compose_block' for t in n.targets))
        tree = ast.parse(ast.literal_eval(literal))
        assignment = next(n for n in tree.body if isinstance(n, ast.AnnAssign) and getattr(n.target, 'id', None) == 'CONTROLLED_COMPOSE_POLICY')
        scope = {'Any': Any}
        exec(compile(ast.Module(body=[assignment],type_ignores=[]), '<policy>', 'exec'), scope)
        self.policy = scope['CONTROLLED_COMPOSE_POLICY']
        self.calls = []
        class MCP:
            def tool(self, **kwargs): return lambda fn: fn
        def base(project, compose):
            if project != PROJECT or compose != COMPOSE:
                raise PermissionError('controlled_compose_file_not_allowed')
            return ['docker','compose','-p',PROJECT,'-f',COMPOSE],COMPOSE,Path('/isolated')
        def run(command, repository, timeout):
            self.calls.append(command)
            return {'ok':True,'exit_code':0}
        scope.update(mcp=MCP(), _controlled_compose_base=base, _run=run)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name=='project_compose_service_execute')
        exec(compile(ast.Module(body=[function],type_ignores=[]), '<executor>', 'exec'),scope)
        self.execute = scope['project_compose_service_execute']
    def call(self, operation, **kwargs):
        args=dict(project_id=PROJECT,compose_file=COMPOSE,service=SERVICE,operation=operation,confirm='EXECUTAR')
        args.update(kwargs)
        return self.execute(**args)
    def test_build_and_run_once_exact_commands(self):
        self.assertTrue(self.call('build')['ok'])
        self.assertEqual(self.calls[-1][-2:],['build',SERVICE])
        self.assertTrue(self.call('run_once')['ok'])
        self.assertEqual(self.calls[-1][-7:],['up','--no-deps','--no-build','--abort-on-container-exit','--exit-code-from',SERVICE,SERVICE])
    def test_persistent_and_destructive_operations_denied(self):
        for operation in ['up','down','restart','exec','pull']:
            self.assertFalse(self.call(operation)['ok'])
        self.assertEqual(self.calls,[])
    def test_no_confirmation_wrong_project_service_or_compose_denied(self):
        for args in [dict(confirm=''),dict(project_id=PROJECT+'-other'),dict(service='core_app'),dict(compose_file='docker-compose.core-hml.yml')]:
            self.assertFalse(self.call('build',**args)['ok'])
        self.assertEqual(self.calls,[])
    def test_only_named_service_and_file_allowed(self):
        policy=self.policy[PROJECT]
        self.assertEqual(policy['compose_files'],{COMPOSE})
        self.assertEqual(policy['services'],{SERVICE})
        self.assertEqual(policy['up'],set())
        self.assertEqual(policy['build'],{SERVICE})
        self.assertEqual(policy['run_once'],{SERVICE})

if __name__=='__main__': unittest.main()
