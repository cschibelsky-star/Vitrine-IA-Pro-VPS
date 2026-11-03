"""Offline V5 VIA-CODE-01 tests: no provider calls, no Docker daemon."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from via_code_pilot_tool import execute_once, PROJECT_ID, EXPERIMENT


class Runner:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {
            "ok": True, "experiment": EXPERIMENT, "model": "anthropic/claude-haiku-5.5",
            "runId": "run_fixture123", "requestId": "req_code01", "reportedCostBRL": "0.001267",
            "inputTokens": 500, "outputTokens": 400,
            "finishReason": "stop", "answer": "diff --git a/src/App.tsx b/src/App.tsx",
        }

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[:2] == ["git", "branch"]:
            return SimpleNamespace(returncode=0, stdout="feature/lab-bootstrap-v040-20261102\n")
        if command[:2] == ["git", "status"]:
            return SimpleNamespace(returncode=0, stdout="")
        if command[:2] == ["docker", "compose"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.response), stderr="")
        raise AssertionError("unexpected command: " + repr(command))


class ViaCodePilotToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / "roteia-ai-lab"
        self.repo = self.workspace / "repository"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / "compose.hml.yml").write_text("services: {}\n")
        (self.repo / "scripts/via-code-pilot.js").write_text("export {}\n")
        (self.workspace / ".env.runtime").write_text("NO_REAL_SECRETS=1\n")
        self.manifest = {
            "id": PROJECT_ID,
            "repository": {"branch": "feature/lab-bootstrap-v040-20261102"},
            "docker": {"compose_file": "compose.hml.yml", "project_name": PROJECT_ID},
            "domains": {"production": []},
        }
        self.runner = Runner()
        self.audits = []

    def run_tool(self, **kwargs):
        return execute_once(
            project_id=kwargs.pop("project_id", PROJECT_ID),
            experiment_id=kwargs.pop("experiment_id", EXPERIMENT),
            confirm=kwargs.pop("confirm", "EXECUTAR"),
            resolve_project=lambda _: (self.manifest, self.workspace, self.repo),
            runner=self.runner, audit=lambda *args: self.audits.append(args),
            expected_workspace=self.workspace,
        )

    def test_denied_without_confirmation_or_for_other_projects(self):
        self.assertEqual(self.run_tool(confirm="")["error"], "confirmation_required")
        self.assertEqual(self.run_tool(project_id="via")["error"], "experiment_or_project_not_allowed")
        self.assertEqual(self.run_tool(experiment_id="VIA-CODE-02")["error"], "experiment_or_project_not_allowed")
        self.assertEqual(self.runner.calls, [])

    def test_only_fixed_docker_run_reaches_isolated_pilot(self):
        out = self.run_tool()
        self.assertTrue(out["ok"])
        self.assertIn("diff --git", out["answer"])
        self.assertEqual(out["reportedCostBRL"], "0.001267")
        self.assertEqual(out["requestId"], "req_code01")
        self.assertEqual(len(self.runner.calls), 3)
        cmd = self.runner.calls[2]
        self.assertEqual(cmd[:5], ["docker", "compose", "-p", PROJECT_ID, "-f"])
        self.assertEqual(cmd[-2:], ["roteia-ai-lab", "scripts/via-code-pilot.js"])
        self.assertNotIn("up", cmd)
        self.assertNotIn("restart", cmd)
        self.assertFalse(any("rt-live" in str(arg) for arg in cmd))
        self.assertEqual(len(self.audits), 1)
        self.assertNotIn("diff --git", str(self.audits))

    def test_clean_branch_and_isolated_environment_required(self):
        self.manifest["docker"]["compose_file"] = "other.yml"
        self.assertEqual(self.run_tool()["error"], "compose_manifest_mismatch")
        self.manifest["docker"]["compose_file"] = "compose.hml.yml"
        self.manifest["domains"]["production"] = ["main"]
        self.assertEqual(self.run_tool()["error"], "production_target_not_allowed")
        self.assertFalse(self.runner.calls)

    def test_unknown_response_does_not_trigger_another_paid_call(self):
        self.runner.response = {"ok": False, "experiment": EXPERIMENT,
                                "runId": "run_x", "error": "transport_error_charge_possible"}
        out = self.run_tool()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "charge_unknown")
        self.assertEqual(sum(c[:2] == ["docker", "compose"] for c in self.runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
