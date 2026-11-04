"""Offline tests for the Roteia transport, the MCP-facing tool and its installer.

No network: the HTTP client is a fake injected through client_factory.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_work_delegate as core  # noqa: E402
import ai_work_delegate_tool as tool  # noqa: E402
import roteia_transport as transport_mod  # noqa: E402

INSTALLER = HERE / "install_ai_work_delegate.py"
ACCEPTANCE = HERE / "acceptance_ai_work_delegate.py"
SECRET = "sk-test-SECRET-123456"
BASE_ENV = {
    "ROTEIA_API_KEY": SECRET,
    "ROTEIA_MODEL_ID": "testprovider/claude-test-model",
    "ROTEIA_PRICE_INPUT_CENTS_PER_MTOK": "500",
    "ROTEIA_PRICE_OUTPUT_CENTS_PER_MTOK": "2500",
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {
            "id": "resp-1",
            "model": "testprovider/claude-test-model",
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 2},
        }

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, calls, response):
        self.calls, self.response = calls, response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ToolCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.env = {**BASE_ENV, tool.LEDGER_ENV: str(self.dir / "ledger.sqlite")}
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def factory(self, response=None):
        response = response if response is not None else FakeResponse()
        return lambda: FakeClient(self.calls, response)

    def run_tool(self, key="exp-1", cents=100, confirm="EXECUTAR", response=None, env=None, **kw):
        kw.setdefault("require_mount", False)
        kw.setdefault("forbidden_roots", ())
        return tool.run_delegate(
            key, "Responda OK", cents, confirm,
            env=self.env if env is None else env, client_factory=self.factory(response), **kw,
        )


class TransportConfigTests(unittest.TestCase):
    def problems(self, **overrides):
        env = {**BASE_ENV, **overrides}
        return transport_mod.inspect_config(env)[1]

    def test_valid_config_has_no_problems(self):
        self.assertEqual(self.problems(), [])

    def test_missing_pieces_are_reported_as_codes_only(self):
        self.assertEqual(self.problems(ROTEIA_API_KEY=""), ["roteia_api_key_missing"])
        self.assertEqual(self.problems(ROTEIA_MODEL_ID=""), ["roteia_model_not_configured"])
        self.assertEqual(self.problems(ROTEIA_PRICE_INPUT_CENTS_PER_MTOK=""), ["roteia_tariff_not_configured"])
        self.assertEqual(self.problems(ROTEIA_PRICE_OUTPUT_CENTS_PER_MTOK="0"), ["roteia_tariff_not_configured"])
        self.assertEqual(self.problems(ROTEIA_PRICE_INPUT_CENTS_PER_MTOK="abc"), ["roteia_tariff_not_configured"])

    def test_model_must_be_provider_slash_claude(self):
        self.assertEqual(self.problems(ROTEIA_MODEL_ID="claude-sonnet"), ["roteia_model_not_configured"])
        self.assertEqual(self.problems(ROTEIA_MODEL_ID="openai/gpt-x"), ["roteia_model_not_configured"])

    def test_url_is_pinned_to_roteia_host(self):
        for url in ("http://api.roteia.ai/v1/chat/completions",
                    "https://evil.example/v1/chat/completions",
                    "https://api.roteia.ai.evil.example/v1/chat/completions",
                    "https://user:pw@api.roteia.ai/v1/chat/completions"):
            self.assertEqual(self.problems(ROTEIA_API_URL=url), ["roteia_url_not_approved"], url)

    def test_max_output_tokens_bounds(self):
        self.assertEqual(self.problems(ROTEIA_MAX_OUTPUT_TOKENS="99999"), ["roteia_max_output_tokens_invalid"])
        self.assertEqual(self.problems(ROTEIA_MAX_OUTPUT_TOKENS="x"), ["roteia_max_output_tokens_invalid"])
        self.assertEqual(self.problems(ROTEIA_MAX_OUTPUT_TOKENS="256"), [])

    def test_api_key_hidden_from_repr(self):
        config = transport_mod.load_config(BASE_ENV)
        self.assertNotIn(SECRET, repr(config))

    def test_worst_case_cost_rounds_up(self):
        config = transport_mod.load_config(BASE_ENV)
        # (1000 bytes + 64) * 500 / 1e6 = 0.532 ; 1024 * 2500 / 1e6 = 2.56 ; total 3.092 -> 4
        self.assertEqual(transport_mod.worst_case_cents(config, "a" * 1000), 4)
        self.assertEqual(transport_mod.worst_case_cents(config, "á" * 1000), 4)  # 2 bytes each: still bounded


class DelegateToolTests(ToolCase):
    def test_confirmation_required_and_nothing_happens(self):
        result = self.run_tool(confirm="")
        self.assertEqual(result["error"], "confirmation_required")
        self.assertEqual(self.calls, [])
        self.assertFalse((self.dir / "ledger.sqlite").exists())

    def test_unconfigured_roteia_makes_no_call_and_no_reservation(self):
        env = {tool.LEDGER_ENV: self.env[tool.LEDGER_ENV]}
        result = self.run_tool(env=env)
        self.assertEqual(result["error"], "roteia_api_key_missing")
        self.assertEqual(self.calls, [])
        self.assertEqual(core.DelegateLedger(self.dir / "ledger.sqlite").status()["reserved_cents"], 0)

    def test_success_request_shape_single_post_and_no_secret_in_result(self):
        result = self.run_tool()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["settlement"], "pending_verification")
        self.assertEqual(result["provider_response"]["text"], "OK")
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call["url"], "https://api.roteia.ai/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {SECRET}")
        self.assertEqual(call["json"]["model"], "testprovider/claude-test-model")
        self.assertEqual(call["json"]["messages"], [{"role": "user", "content": "Responda OK"}])
        self.assertEqual(call["json"]["max_tokens"], 1024)
        self.assertIs(call["json"]["stream"], False)
        self.assertNotIn(SECRET, json.dumps(result))
        ledger = core.DelegateLedger(self.dir / "ledger.sqlite").status()
        self.assertEqual(ledger["reserved_cents"], 100)
        self.assertIn("charge_uncertain", ledger["by_status"])

    def test_duplicate_experiment_never_calls_provider_twice(self):
        self.assertTrue(self.run_tool()["ok"])
        second = self.run_tool()
        self.assertEqual(second["error"], "duplicate_or_uncertain_charge")
        self.assertEqual(len(self.calls), 1)

    def test_total_cap_is_enforced_across_experiments(self):
        self.assertTrue(self.run_tool("a", 600)["ok"])
        blocked = self.run_tool("b", 500)
        self.assertEqual(blocked["error"], "total_budget_exceeded")
        self.assertEqual(len(self.calls), 1)

    def test_cost_bound_refusal_happens_before_reservation(self):
        # worst case for this short prompt and tariff is 3 cents; reserving 2 must be
        # refused up front, without touching the ledger or the provider.
        self.assertEqual(
            transport_mod.worst_case_cents(transport_mod.load_config(BASE_ENV), "Responda OK"), 3
        )
        result = self.run_tool(cents=2)
        self.assertEqual(result["error"], "cost_bound_exceeds_reservation")
        self.assertEqual(self.calls, [])
        self.assertEqual(core.DelegateLedger(self.dir / "ledger.sqlite").status()["reserved_cents"], 0)

    def test_http_error_keeps_budget_reserved_and_hides_detail(self):
        result = self.run_tool(response=FakeResponse(status_code=500))
        self.assertEqual(result["error"], "provider_failure_charge_possible")
        self.assertNotIn(SECRET, json.dumps(result))
        ledger = core.DelegateLedger(self.dir / "ledger.sqlite").status()
        self.assertEqual(ledger["reserved_cents"], 100)
        self.assertEqual(self.run_tool()["error"], "duplicate_or_uncertain_charge")
        self.assertEqual(len(self.calls), 1)

    def test_network_exception_is_not_retried(self):
        result = self.run_tool(response=TimeoutError("boom " + SECRET))
        self.assertEqual(result["error"], "provider_failure_charge_possible")
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertEqual(len(self.calls), 1)

    def test_malformed_provider_payload_is_charge_uncertain(self):
        result = self.run_tool(response=FakeResponse(payload={"unexpected": True}))
        self.assertEqual(result["error"], "provider_failure_charge_possible")
        self.assertEqual(core.DelegateLedger(self.dir / "ledger.sqlite").status()["reserved_cents"], 100)

    def test_ledger_inside_restorable_tree_is_refused(self):
        result = self.run_tool(forbidden_roots=(str(self.dir),))
        self.assertEqual(result["error"], "ledger_in_restorable_tree")
        self.assertEqual(self.calls, [])

    def test_ledger_must_be_on_a_mounted_volume(self):
        result = self.run_tool(require_mount=True)
        self.assertEqual(result["error"], "ledger_not_on_persistent_volume")
        self.assertEqual(self.calls, [])

    def test_ledger_path_must_be_absolute_and_dir_must_exist(self):
        self.assertEqual(self.run_tool(env={**BASE_ENV, tool.LEDGER_ENV: "ledger.sqlite"})["error"],
                         "ledger_path_not_absolute")
        missing = {**BASE_ENV, tool.LEDGER_ENV: str(self.dir / "nope" / "ledger.sqlite")}
        self.assertEqual(self.run_tool(env=missing)["error"], "ledger_dir_missing")


class StatusTests(ToolCase):
    def status(self, env=None, **kw):
        kw.setdefault("require_mount", False)
        kw.setdefault("forbidden_roots", ())
        return tool.delegate_status(self.env if env is None else env, **kw)

    def test_ready_when_ledger_and_roteia_are_configured(self):
        status = self.status()
        self.assertTrue(status["ledger"]["ready"])
        self.assertTrue(status["ready_for_paid_call"])
        self.assertEqual(status["ledger"]["available_cents"], 1000)
        self.assertNotIn(SECRET, json.dumps(status))

    def test_ledger_ready_even_if_roteia_not_configured(self):
        status = self.status(env={tool.LEDGER_ENV: self.env[tool.LEDGER_ENV]})
        self.assertTrue(status["ledger"]["ready"])
        self.assertFalse(status["ready_for_paid_call"])
        self.assertIn("roteia_api_key_missing", status["roteia"]["problems"])

    def test_ledger_not_ready_in_restorable_tree(self):
        status = self.status(forbidden_roots=(str(self.dir),))
        self.assertFalse(status["ledger"]["ready"])
        self.assertEqual(status["ledger"]["error"], "ledger_in_restorable_tree")

    def test_default_mount_requirement_flags_non_persistent_dir(self):
        status = self.status(require_mount=True)
        self.assertEqual(status["ledger"]["error"], "ledger_not_on_persistent_volume")


MAIN_PY = (
    "from typing import Any\n\nfrom server import mcp\n\n"
    "@mcp.tool()\ndef connector_health() -> dict[str, Any]:\n    return {}\n\n"
    'if __name__ == "__main__":\n    pass\n'
)
OVERRIDE = (
    "services:\n"
    "  ops_broker:\n"
    "    environment:\n"
    "      TVSUMARE_ROOT: /srv/tvsumare\n"
    "  vps_mcp_connector:\n"
    "    environment:\n"
    "      TVSUMARE_ROOT: /srv/tvsumare\n"
    "    volumes:\n"
    "      - /srv/tvsumare:/host/tvsumare:ro\n"
)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / "connector"
        self.root.mkdir()
        self.ledger_dir = base / "ledger-data"
        (self.root / "main.py").write_text(MAIN_PY, encoding="utf-8")
        (self.root / "Dockerfile").write_text("FROM python:3.12\nCOPY server.py main.py ./\n", encoding="utf-8")
        (self.root / "docker-compose.connector-v2.override.yml").write_text(OVERRIDE, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def install(self, host_dir=None):
        env = {**os.environ, "CONNECTOR_ROOT": str(self.root),
               "AI_WORK_DELEGATE_HOST_DIR": str(host_dir or self.ledger_dir)}
        return subprocess.run([sys.executable, str(INSTALLER)], capture_output=True, text=True, env=env)

    def test_install_registers_tools_idempotently(self):
        for _ in range(2):
            result = self.install()
            self.assertEqual(result.returncode, 0, result.stderr)
        main_text = (self.root / "main.py").read_text(encoding="utf-8")
        self.assertEqual(main_text.count("def ai_work_delegate("), 1)
        self.assertEqual(main_text.count("def ai_work_delegate_status("), 1)
        self.assertEqual(main_text.count("from ai_work_delegate_tool import ("), 1)
        compile(main_text, "main.py", "exec")
        docker_text = (self.root / "Dockerfile").read_text(encoding="utf-8")
        copy_tokens = next(line for line in docker_text.splitlines() if line.startswith("COPY ")).split()
        for module in ("ai_work_delegate.py", "roteia_transport.py", "ai_work_delegate_tool.py",
                       "roteia_delegate_adapter.py", "acceptance_ai_work_delegate.py"):
            self.assertEqual(copy_tokens.count(module), 1, module)
            self.assertTrue((self.root / module).is_file(), module)
        override = (self.root / "docker-compose.connector-v2.override.yml").read_text(encoding="utf-8")
        volume = f"- {self.ledger_dir}:/data/ai-work-delegate:rw"
        self.assertEqual(override.count(volume), 1)
        self.assertEqual(override.count("AI_WORK_DELEGATE_LEDGER: /data/ai-work-delegate/ledger.sqlite"), 1)
        self.assertEqual(override.count("ROTEIA_API_KEY: ${ROTEIA_API_KEY:-}"), 1)
        # entries land in the MCP service, not in ops_broker
        broker, connector = override.split("  vps_mcp_connector:")
        self.assertNotIn("ROTEIA", broker)
        self.assertIn("ROTEIA_API_KEY", connector)
        self.assertTrue(self.ledger_dir.is_dir())

    def test_secret_values_are_never_written(self):
        env = {**os.environ, "CONNECTOR_ROOT": str(self.root),
               "AI_WORK_DELEGATE_HOST_DIR": str(self.ledger_dir), "ROTEIA_API_KEY": SECRET}
        subprocess.run([sys.executable, str(INSTALLER)], check=True, capture_output=True, text=True, env=env)
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET, path.read_text(encoding="utf-8", errors="ignore"), str(path))

    def test_ledger_dir_inside_connector_root_is_refused(self):
        result = self.install(host_dir=self.root / "ledger")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ledger_host_dir_inside_connector_root", result.stderr)
        self.assertEqual((self.root / "main.py").read_text(encoding="utf-8"), MAIN_PY)

    def test_missing_override_fails_instead_of_skipping_volume(self):
        (self.root / "docker-compose.connector-v2.override.yml").unlink()
        result = self.install()
        self.assertNotEqual(result.returncode, 0)


class AcceptanceScriptTests(unittest.TestCase):
    def test_refuses_without_explicit_confirmation(self):
        result = subprocess.run(
            [sys.executable, str(ACCEPTANCE), "--url", "http://127.0.0.1:1/mcp", "--experiment-id", "x"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("confirmation_required", result.stderr)


if __name__ == "__main__":
    unittest.main()
