"""Startup composition checks using only the Python standard library."""
import ast
import unittest
from pathlib import Path

from marketing_live_patch import apply as marketing
from controlled_operations_patch import apply as controlled
from test_controlled_operations_patch import test_recovered_controlled_operations_layer


class StartupCompositionTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(__file__).with_name('main.py').read_text()

    def test_current_baseline_composes_and_compiles(self):
        composed = controlled(marketing(self.base))
        compile(composed, '<composed-runtime>', 'exec')
        functions = [n for n in ast.parse(composed).body if isinstance(n, ast.FunctionDef)]
        names = [n.name for n in functions]
        self.assertEqual(names.count('project_manifest_branch_configure'), 1)
        self.assertIn('project_runtime_secret_import_from_container', names)
        self.assertIn('vps_filesystem_backup', names)
        tool = next(n for n in functions if n.name == 'project_manifest_branch_configure')
        self.assertEqual(len(tool.decorator_list), 1)
        self.assertEqual(ast.unparse(tool.decorator_list[0].func), 'mcp.tool')

    def test_original_runner_version_still_supported(self):
        legacy = self.base.replace('VERSION = "0.5.12-vps-filesystem-backup"', 'VERSION = "0.5.11-generic-laravel-test-runner"')
        compile(controlled(marketing(legacy)), '<legacy-runtime>', 'exec')

    def test_unknown_version_fails_closed(self):
        changed = self.base.replace('VERSION = "0.5.12-vps-filesystem-backup"', 'VERSION = "unknown"')
        with self.assertRaisesRegex(RuntimeError, 'version_match_count:0'):
            marketing(changed)

    def test_ambiguous_baseline_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'version_match_count:2'):
            marketing(self.base + '\nVERSION = "0.5.11-generic-laravel-test-runner"\n')

    def test_missing_runner_anchor_still_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'commands_match_count:0'):
            marketing(self.base.replace('    commands = {', '    changed_commands = {'))

    def test_existing_controlled_operations_regression(self):
        test_recovered_controlled_operations_layer()


if __name__ == '__main__':
    unittest.main()
