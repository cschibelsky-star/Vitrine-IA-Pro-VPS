"""Offline V5 VIA-CODE-01 tests: no provider calls, no Docker daemon."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from via_code_pilot_tool import execute_once, diagnose_readonly, PROJECT_ID, EXPERIMENT


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



class DiagnosticToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / "roteia-ai-lab"
        self.repo = self.workspace / "repository"
        self.repo.mkdir(parents=True)
        self.manifest = {
            "id": PROJECT_ID,
            "docker": {"compose_file": "compose.hml.yml", "project_name": PROJECT_ID},
            "domains": {"production": []},
        }
        self.calls = []

    def diagnose(self, project_id=PROJECT_ID, experiment_id=EXPERIMENT, response=None):
        if response is None:
            response = {
                "experiment": EXPERIMENT, "databaseExists": True, "sqliteWriteAccess": True,
                "credentialPresent": True, "scriptPresent": True, "tableExists": False,
                "attemptRecorded": False, "record": None, "secret": "never-return-this",
            }
        def runner(argv, **kwargs):
            self.calls.append(argv)
            return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")
        return diagnose_readonly(
            project_id=project_id, experiment_id=experiment_id,
            resolve_project=lambda _: (self.manifest, self.workspace, self.repo),
            runner=runner, expected_workspace=self.workspace,
        )

    def test_fixed_readonly_probe_and_sanitization(self):
        result = self.diagnose()
        self.assertTrue(result["ok"])
        self.assertTrue(result["readOnly"])
        self.assertFalse(result["upstreamCalled"])
        self.assertFalse(result["attemptRecorded"])
        self.assertNotIn("secret", result)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][:8], [
            "docker", "exec", "-u", "node", "roteia_ai_lab_hml",
            "node", "--input-type=module", "-e",
        ])
        self.assertNotIn("compose", self.calls[0])
        self.assertNotIn("via-code-pilot.js", self.calls[0][:8])

    def test_rejects_other_project_or_experiment_and_production(self):
        self.assertEqual(self.diagnose(project_id="via")["error"],
                         "experiment_or_project_not_allowed")
        self.assertEqual(self.diagnose(experiment_id="OTHER")["error"],
                         "experiment_or_project_not_allowed")
        self.manifest["domains"]["production"] = ["real-service"]
        self.assertEqual(self.diagnose()["error"], "readonly_scope_mismatch")
        self.assertEqual(self.calls, [])

    def test_returns_only_allowlisted_record_fields(self):
        response = {
            "experiment": EXPERIMENT, "databaseExists": True, "tableExists": True,
            "attemptRecorded": True, "record": {"experiment": EXPERIMENT,
                "status": "charge_unknown", "run_id": "run_1",
                "error_code": "transport_error_charge_possible",
                "api_token": "never-return-this"},
        }
        result = self.diagnose(response=response)
        self.assertTrue(result["attemptRecorded"])
        self.assertEqual(result["record"]["status"], "charge_unknown")
        self.assertNotIn("api_token", result["record"])
        self.assertNotIn("never-return-this", str(result))


if __name__ == "__main__":
    unittest.main()
