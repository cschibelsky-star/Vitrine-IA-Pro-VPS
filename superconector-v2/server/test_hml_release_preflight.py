import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import hml_release_preflight as release
import maintenance_broker as broker
import maintenance_client as client


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = SimpleNamespace(root=self.root, docker_project="pilot-hml", services=("app",))
        self.head = "a" * 40
        self.target = "b" * 40
        self.cid = "c" * 64
        self.image = "sha256:" + "d" * 64

    def docker(self, project="pilot-hml", state="running", health="healthy"):
        return Mock(side_effect=[self.cid, f"{self.cid}|{project}|app|{self.image}|{state}|{health}"])

    @patch.object(release, "git")
    def test_reports_exact_image_and_does_not_mutate_workspace(self, git):
        git.side_effect = [self.head.encode(), b"", b"commit\n"]
        docker = self.docker()
        result = release.preflight(self.project, self.target, docker)
        self.assertEqual(result["workspace_head"], self.head)
        self.assertEqual(result["services"][0]["current_image"], self.image)
        self.assertEqual(result["blockers"], [])
        self.assertEqual([call.args[1] for call in git.call_args_list], ["rev-parse", "status", "cat-file"])
        self.assertEqual([call.args[0] for call in docker.call_args_list], ["ps", "inspect"])

    @patch.object(release, "git")
    def test_reports_dirty_missing_commit_and_unhealthy(self, git):
        git.side_effect = [self.head.encode(), b" M changed\0", subprocess.CalledProcessError(1, "cat-file")]
        result = release.preflight(self.project, self.target, self.docker(health="unhealthy"))
        self.assertEqual(result["blockers"], [
            "workspace_has_local_changes", "commit_not_present_locally", "runtime_service_unavailable",
        ])

    def test_does_not_accept_refs_shell_arguments_or_mismatched_identity(self):
        docker = Mock()
        for value in ("main", "--all", self.target[:12], "../test", None):
            with self.assertRaises(ValueError):
                release.preflight(self.project, value, docker)
        docker.assert_not_called()
        with self.assertRaises(PermissionError):
            release.runtime(self.docker(project="production"), "pilot-hml", "app")

    def test_multiple_containers_are_reported_as_ambiguous(self):
        docker = Mock(return_value=f"{self.cid}\n{self.cid}")
        self.assertEqual(release.runtime(docker, "pilot-hml", "app"), {"service": "app", "status": "ambiguous"})
        docker.assert_called_once()

    def test_broker_and_client_restrict_project_and_operation(self):
        op = "project_hml_release_preflight"
        with self.assertRaises(PermissionError):
            broker.operation({"operation": op, "project_id": "production", "commit": self.target})
        with self.assertRaises(ValueError):
            broker.operation({"operation": op, "project_id": "cockpit-admin-v1-hml", "commit": self.target, "command": "up"})
        token = SimpleNamespace(subject="operator", scopes=["projects:read"])
        client.authorize(token, op, "operator", True)
