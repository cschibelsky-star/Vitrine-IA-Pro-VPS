import importlib.util
import pathlib
import subprocess
import tempfile
import types
import unittest

EXPERIMENT = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("isolated_runner", EXPERIMENT / "runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
SERVER = EXPERIMENT.parents[1] / "server"
SHA = "a" * 40


class RunnerTests(unittest.TestCase):
    def run_one(self, profile="probe", **changes):
        config = dict(profile=profile, server_root=SERVER, approval="EXECUTAR",
                      context="isolated-ci-only", source_sha=SHA)
        config.update(changes)
        return runner.run_profile(**config)

    def test_actual_linux_probe_subprocess(self):
        value = self.run_one()
        self.assertTrue(value["ok"], value)
        self.assertEqual(value["exit_code"], 0)
        self.assertIn("vitrine_executor_probe_ok", value["stdout"])
        self.assertFalse(value["dispatch_allowed"])

    def test_actual_code_syntax_check(self):
        value = self.run_one("syntax")
        self.assertTrue(value["ok"], value)
        self.assertIn("vitrine_executor_syntax_ok", value["stdout"])

    def test_unknown_profile_denied(self):
        self.assertEqual(self.run_one("bash").get("reason"), "profile_not_allowed")

    def test_no_confirmation_denied(self):
        self.assertEqual(self.run_one(approval="").get("reason"), "authorization_or_context_missing")

    def test_non_ci_context_denied(self):
        self.assertEqual(self.run_one(context="production").get("reason"), "authorization_or_context_missing")

    def test_invalid_sha_denied(self):
        self.assertEqual(self.run_one(source_sha="HEAD").get("reason"), "source_sha_invalid")

    def test_nonexistent_root_denied(self):
        self.assertEqual(self.run_one(server_root="/nonexistent/runner-root").get("reason"), "runner_failed_or_timed_out")

    def test_fake_workspace_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(self.run_one(server_root=temp).get("reason"), "workspace_files_missing_or_symlinked")

    def test_failed_subprocess_is_not_pass(self):
        def failed(args, **kwargs):
            return types.SimpleNamespace(stdout="", stderr="synthetic failure", returncode=3)
        x = self.run_one(runner=failed)
        self.assertFalse(x["ok"])
        self.assertEqual(x["exit_code"], 3)
        self.assertEqual(x["status"], "failed")

    def test_output_is_limited(self):
        def noisy(args, **kwargs):
            return types.SimpleNamespace(stdout="X"*8000, stderr="Y"*8000, returncode=0)
        x = self.run_one(runner=noisy)
        self.assertEqual(len(x["stdout"]), 4096)
        self.assertEqual(len(x["stderr"]), 4096)
        self.assertTrue(x["output_truncated"])

    def test_no_shell_or_inherited_secrets(self):
        seen = {}
        def inspect(args, **kwargs):
            seen.update(kwargs)
            return types.SimpleNamespace(stdout="ok", stderr="", returncode=0)
        self.run_one(runner=inspect)
        self.assertIs(seen["shell"], False)
        self.assertNotIn("GITHUB_TOKEN", seen["env"])
        self.assertNotIn("OPENAI_API_KEY", seen["env"])
        self.assertEqual(seen["timeout"], 10)
        self.assertEqual(seen["cwd"], str(SERVER.resolve()))

    def test_no_production_activation_fields(self):
        self.assertFalse(self.run_one()["production_allowed"])
        self.assertFalse(self.run_one()["dispatch_allowed"])


if __name__ == "__main__":
    unittest.main()
