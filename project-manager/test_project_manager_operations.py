"""Regression tests for Docker diagnostics. Run with python -m unittest discover -s project-manager."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


try:
    import fastapi  # noqa: F401
    import pydantic  # noqa: F401
except ImportError:
    # Allow the pure endpoint logic to run in a minimal checkout without server deps.
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda func: func

        post = get

    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            self.status_code, self.detail = status_code, detail

    fastapi.APIRouter = APIRouter
    fastapi.Depends = lambda func: func
    fastapi.Header = lambda default=None: default
    fastapi.HTTPException = HTTPException
    sys.modules["fastapi"] = fastapi
    pydantic = types.ModuleType("pydantic")

    class BaseModel:
        def __init__(self, **fields):
            self.__dict__.update(fields)

        def model_dump(self):
            return dict(self.__dict__)

    pydantic.BaseModel = BaseModel
    sys.modules["pydantic"] = pydantic


MODULE_PATH = Path(__file__).with_name("project_manager_operations.py")
spec = importlib.util.spec_from_file_location("project_manager_operations", MODULE_PATH)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


class DockerDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.request = ops.ProjectContainerRequest(
            project_id="example", container_name="vitrine_core_example"
        )
        self.manifest = {"workspace_root": "/srv/projects/not-created"}

    def test_redacts_credentials_in_urls_and_dsns_without_changing_safe_values(self):
        values = ops.redact_container_env([
            "DATABASE_URL=mysql://user:pass@db.local/app",
            "REDIS_URL=redis://:pass@redis.local:6379/0",
            "JDBC_URL=jdbc:mysql://db.local/app?user=u&password=p",
            "CONNECTION=host=db.local user=u password=p dbname=app",
            "SERVICE_URL=https://example.test/path?access_token=abc",
            "DB_PASSWORD=already-sensitive",
            "PUBLIC_URL=https://example.test/path?mode=read",
            "PORT=8080",
            "BROKEN",
        ])
        for key in ("DATABASE_URL", "REDIS_URL", "JDBC_URL", "CONNECTION", "SERVICE_URL", "DB_PASSWORD"):
            self.assertEqual(values[key], "***REDACTED***")
        self.assertEqual(values["PUBLIC_URL"], "https://example.test/path?mode=read")
        self.assertEqual(values["PORT"], "8080")
        self.assertNotIn("BROKEN", values)

    def test_large_inspect_without_workspace_and_audit_contains_only_redacted_env(self):
        item = {
            "Name": "/vitrine_core_example",
            "Config": {"Image": "app:latest", "Env": [
                "DATABASE_URL=postgresql://alice:super-secret@db.local/app",
                "PUBLIC_URL=https://example.test",
            ]},
            "State": {"Status": "running", "Running": True},
            "NetworkSettings": {"Networks": {}, "Ports": {}},
            "LargeLabel": "x" * 60000,
        }
        output = json.dumps([item])
        self.assertGreater(len(output), 50000)
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(ops, "load_manifest", return_value=self.manifest), \
             patch.object(ops.subprocess, "run", side_effect=fake_run), \
             patch.object(ops, "AUDIT_LOG", Path(directory) / "audit.jsonl"):
            self.assertFalse(Path(self.manifest["workspace_root"]).exists())
            info = ops.project_docker_container_info(self.request)
            safe = ops.project_docker_container_env_safe(self.request)
            audit_text = ops.AUDIT_LOG.read_text()

        self.assertEqual(info["container"]["status"], "running")
        self.assertEqual(safe["environment"]["DATABASE_URL"], "***REDACTED***")
        self.assertEqual(safe["environment"]["PUBLIC_URL"], "https://example.test")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(command == ["docker", "inspect", "vitrine_core_example"] for command, _ in calls))
        self.assertTrue(all(kwargs["cwd"] is None for _, kwargs in calls))
        self.assertNotIn("super-secret", audit_text)
        self.assertEqual(json.loads(audit_text.splitlines()[-1])["result"], safe)

    def test_regular_command_output_retains_existing_limit(self):
        with patch.object(ops.subprocess, "run", return_value=subprocess.CompletedProcess(
            ["git"], 0, stdout="x" * 60000, stderr=""
        )):
            self.assertEqual(len(ops.run(["git"], Path("/tmp"))["stdout"]), 50000)


if __name__ == "__main__":
    unittest.main()
