"""Compose runtime metadata regression tests: no Docker or secret access."""
import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from marketing_live_patch import apply as marketing
from controlled_operations_patch import apply as controlled


class ComposeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.repo = self.workspace / "repository"
        self.repo.mkdir()
        self.runtime = self.workspace / ".env.runtime"
        self.runtime.write_text("FIXTURE_ONLY=not-a-secret\n")
        self.manifest = {
            "id": "tvsumare", "workspace_root": str(self.workspace),
            "repository": {"directory": "repository"},
            "docker": {"project_name": "tvsumare"},
            "runtime": {"env_file": ".env.runtime", "allowed_keys": []},
        }
        base = Path(__file__).with_name("main.py").read_text()
        tree = ast.parse(controlled(marketing(base)))
        names = {"_controlled_runtime_env_path", "_controlled_compose_base",
                 "project_compose_service_status", "project_compose_service_execute",
                 "_runtime_config", "_within", "_validated_workspace_root"}
        nodes = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                node.decorator_list = []
                nodes.append(node)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "CONTROLLED_COMPOSE_POLICY":
                nodes.append(node)
        self.run = Mock(return_value={"ok": True, "stdout": "fixture"})
        self.ns = {
            "Path": Path, "Any": object,
            "ALLOWED_WORKSPACE_ROOTS": (self.workspace,),
            "_safe_file": lambda project, path, required: (self.repo / path, path),
            "_project_paths": lambda project: (self.manifest, self.workspace, self.repo),
            "_run": self.run,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "<isolated-compose>", "exec"), self.ns)

    def status(self, **args):
        values = dict(project_id="tvsumare", compose_file="docker-compose.vps.yml", service="web")
        values.update(args)
        return self.ns["project_compose_service_status"](**values)

    def test_empty_secret_allowlist_does_not_block_status(self):
        self.assertTrue(self.status()["ok"])
        command = self.run.call_args.args[0]
        self.assertIn(str(self.runtime), command)
        self.assertEqual(command[-3:], ["ps", "-a", "web"])
        self.assertNotIn("not-a-secret", str(command))

    def test_empty_secret_allowlist_still_blocks_secret_editing(self):
        with self.assertRaisesRegex(PermissionError, "runtime_keys_not_configured"):
            self.ns["_runtime_config"](self.manifest)

    def test_missing_runtime_file_fails_without_running_docker(self):
        self.runtime.unlink()
        self.assertEqual(self.status()["error"], "runtime_env_not_configured")
        self.run.assert_not_called()

    def test_absolute_and_parent_paths_are_rejected(self):
        for path in ("/tmp/runtime", "../runtime", "..\\runtime", ""):
            with self.subTest(path=path):
                self.manifest["runtime"]["env_file"] = path
                self.assertEqual(self.status()["error"], "invalid_runtime_env_file")
        self.run.assert_not_called()

    def test_symlink_escape_is_rejected(self):
        outside = self.root / "outside-runtime"
        outside.write_text("fixture")
        self.runtime.unlink()
        self.runtime.symlink_to(outside)
        self.assertEqual(self.status()["error"], "runtime_env_outside_workspace")
        self.run.assert_not_called()

    def test_service_and_compose_allowlists_are_preserved(self):
        self.assertEqual(self.status(service="web_prod")["error"], "controlled_service_not_allowed")
        self.assertEqual(self.status(compose_file="other.yml")["error"], "controlled_compose_file_not_allowed")
        self.run.assert_not_called()

    def test_execution_requires_confirmation(self):
        result = self.ns["project_compose_service_execute"](
            "tvsumare", "docker-compose.vps.yml", "web", "up")
        self.assertEqual(result["error"], "confirmation_required")
        self.run.assert_not_called()

    def test_authorized_up_is_still_scoped_to_one_service(self):
        result = self.ns["project_compose_service_execute"](
            "tvsumare", "docker-compose.vps.yml", "web", "up", "EXECUTAR")
        self.assertTrue(result["ok"])
        self.assertEqual(self.run.call_args.args[0][-5:],
                         ["up", "-d", "--no-deps", "--no-build", "web"])


if __name__ == "__main__":
    unittest.main()
