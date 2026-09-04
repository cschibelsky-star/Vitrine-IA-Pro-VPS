import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class BreakGlassApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["BREAK_GLASS_TOKEN"] = "unit-test-token"
        cls.app = load_module("break_glass_app_test", "app.py")

    def setUp(self):
        self.app._REQUESTS.clear()

    def test_authorization_accepts_only_exact_bearer_token(self):
        self.assertTrue(self.app._authorized("Bearer unit-test-token"))
        self.assertFalse(self.app._authorized(None))
        self.assertFalse(self.app._authorized("unit-test-token"))
        self.assertFalse(self.app._authorized("Bearer wrong-token"))
        self.assertFalse(self.app._authorized("Basic unit-test-token"))

    def test_rate_limit_is_fail_closed_after_limit(self):
        client = "203.0.113.10"
        with patch.object(self.app, "RATE_MAX_REQUESTS", 2), patch.object(self.app, "RATE_WINDOW_SECONDS", 60):
            self.assertTrue(self.app._rate_allowed(client))
            self.assertTrue(self.app._rate_allowed(client))
            self.assertFalse(self.app._rate_allowed(client))


class ExecutorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executor = load_module("break_glass_executor_test", "executor.py")

    def setUp(self):
        self.audit_patch = patch.object(self.executor, "_audit")
        self.audit_patch.start()
        self.addCleanup(self.audit_patch.stop)

    def test_unknown_operation_is_rejected_without_command_execution(self):
        with patch.object(self.executor, "_run") as run:
            result = self.executor._handle({"op": "shell", "command": "id"})
        self.assertEqual(result, {"ok": False, "error": "operation_not_allowed"})
        run.assert_not_called()

    def test_logs_use_fixed_container_and_clamp_line_count(self):
        fake = {"ok": True, "exit_code": 0, "stdout": "ok", "stderr": ""}
        with patch.object(self.executor, "_run", return_value=fake) as run:
            result = self.executor._handle({"op": "logs", "lines": 999999, "container": "evil"})
        self.assertTrue(result["ok"])
        run.assert_called_once_with(
            ["docker", "logs", "--tail", str(self.executor.MAX_LOG_LINES), self.executor.V5_CONTAINER],
            timeout=15,
        )

    def test_restart_uses_fixed_container_only(self):
        fake = {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}
        with patch.object(self.executor, "_run", return_value=fake) as run:
            result = self.executor._handle({"op": "restart", "container": "evil"})
        self.assertTrue(result["ok"])
        run.assert_called_once_with(
            ["docker", "restart", "--time", "10", self.executor.V5_CONTAINER],
            timeout=30,
        )

    def test_rollback_rejects_arbitrary_release_before_docker_access(self):
        with patch.object(self.executor, "_run") as run:
            result = self.executor._handle({"op": "rollback", "release_id": "attacker-release"})
        self.assertEqual(result, {"ok": False, "error": "release_not_allowed"})
        run.assert_not_called()

    def test_rollback_rejects_noncanonical_compose_path(self):
        with patch.object(self.executor, "V5_COMPOSE_FILE", "/tmp/evil.yml"), patch.object(self.executor, "_run") as run:
            result = self.executor._handle({"op": "rollback", "release_id": self.executor.RELEASE_ID})
        self.assertEqual(result, {"ok": False, "error": "compose_path_blocked"})
        run.assert_not_called()

    def test_contract_contains_no_generic_shell_operation(self):
        source = (ROOT / "executor.py").read_text(encoding="utf-8")
        self.assertNotIn('op == "shell"', source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system(", source)


class WatchdogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.watchdog = load_module("break_glass_watchdog_test", "watchdog.py")

    def test_probe_is_tcp_based(self):
        fake_socket = unittest.mock.MagicMock()
        fake_socket.__enter__.return_value = fake_socket
        fake_socket.__exit__.return_value = False
        with patch.object(self.watchdog.socket, "create_connection", return_value=fake_socket) as create:
            self.assertTrue(self.watchdog._healthy())
        create.assert_called_once_with((self.watchdog.WATCH_HOST, self.watchdog.WATCH_PORT), timeout=3)

    def test_probe_failure_returns_false(self):
        with patch.object(self.watchdog.socket, "create_connection", side_effect=OSError("down")):
            self.assertFalse(self.watchdog._healthy())


if __name__ == "__main__":
    unittest.main()
