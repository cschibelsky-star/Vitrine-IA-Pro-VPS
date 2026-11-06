import os
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge

class BridgeTests(unittest.TestCase):
    def test_calls_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(bridge.ask("ok")["status"], "blocked")
            self.assertEqual(bridge.ask("ok", "claude")["status"], "blocked")
    def test_provider_validation(self):
        self.assertEqual(bridge.ask("ok", "other")["reason"], "unsupported_provider")
    def test_prompt_validation(self):
        self.assertEqual(bridge.ask("")["reason"], "invalid_prompt")
        self.assertEqual(bridge.ask("x" * 12001)["reason"], "invalid_prompt")
    def test_gpt_reject_unknown_model(self):
        with patch.dict(os.environ, {"AVELLO_CALLS_ENABLED":"true"}, clear=True):
            self.assertEqual(bridge.ask("ok", "gpt", "unknown")["reason"], "unsupported_model")
    def test_gpt_mock(self):
        env={"AVELLO_CALLS_ENABLED":"true","AVELLO_GPT_API_KEY":"fake"}
        with patch.dict(os.environ,env,clear=True):
            with patch.object(bridge,"_call",return_value={"model":"gpt-5.6-terra","output":[{"content":[{"type":"output_text","text":"ok"}]}]}):
                result=bridge.ask("hello")
                self.assertEqual(result["status"],"ok")
                self.assertEqual(result["text"],"ok")
    def test_claude_requires_configured_model(self):
        with patch.dict(os.environ,{"AVELLO_CALLS_ENABLED":"true"},clear=True):
            self.assertEqual(bridge.ask("ok","claude")["reason"],"claude_model_unverified")
    def test_claude_mock(self):
        env={"AVELLO_CALLS_ENABLED":"true","AVELLO_CLAUDE_API_KEY":"fake","AVELLO_CLAUDE_MODEL":"claude-test"}
        with patch.dict(os.environ,env,clear=True):
            with patch.object(bridge,"_call",return_value={"model":"claude-test","content":[{"type":"text","text":"ok"}]}):
                result=bridge.ask("hello","claude")
                self.assertEqual(result["text"],"ok")
    def test_http_error_no_token_echo(self):
        env={"AVELLO_CALLS_ENABLED":"true","AVELLO_GPT_API_KEY":"secret-test-value"}
        with patch.dict(os.environ,env,clear=True):
            with patch.object(bridge,"_call",return_value={"status":"provider_error","http_status":401}):
                result=bridge.ask("hello")
                self.assertEqual(result,{"status":"provider_error","http_status":401})
                self.assertNotIn("secret-test-value",str(result))


class DefaultModelTests(unittest.TestCase):
    def test_default_gpt_uses_selected_model_and_excludes_astra(self):
        env={"AVELLO_CALLS_ENABLED":"true","AVELLO_GPT_API_KEY":"fake"}
        with patch.dict(os.environ,env,clear=True):
            with patch.object(bridge,"_call",return_value={"output":[]}) as call:
                result=bridge.ask("test")
        self.assertEqual(result["requested_model"],"gpt-6.1-sol")
        self.assertEqual(call.call_args.args[2]["model"],"gpt-6.1-sol")
        self.assertFalse(any("astra" in m for m in bridge.GPT_MODELS))
    def test_default_claude_uses_runtime_model(self):
        env={"AVELLO_CALLS_ENABLED":"true","AVELLO_CLAUDE_API_KEY":"fake","AVELLO_CLAUDE_MODEL":"claude-opus-5"}
        with patch.dict(os.environ,env,clear=True):
            with patch.object(bridge,"_call",return_value={"content":[]}) as call:
                result=bridge.ask("test","claude")
        self.assertEqual(result["requested_model"],"claude-opus-5")
        self.assertEqual(call.call_args.args[2]["model"],"claude-opus-5")

class CatalogTests(unittest.TestCase):
    def setUp(self):
        bridge._CATALOG_CACHE.clear()
    def tearDown(self):
        bridge._CATALOG_CACHE.clear()
    def test_catalog_reads_once_without_inference(self):
        import io
        from unittest.mock import Mock
        opener = Mock()
        opener.open.side_effect = lambda *a, **k: io.BytesIO(b'{"data":[{"id":"gpt-test"},{"id":"claude-test"}]}')
        with patch.dict(os.environ, {"AVELLO_GPT_API_KEY":"fake"}, clear=True):
            with patch.object(bridge.urllib.request,"build_opener",return_value=opener):
                with patch.object(bridge,"_call",side_effect=AssertionError("inference forbidden")):
                    one=bridge.list_models("gpt")
                    self.assertEqual(one["models"],["claude-test","gpt-test"])
                    self.assertEqual(one,bridge.list_models("gpt"))
        self.assertEqual(opener.open.call_count,1)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.method,"GET")
        self.assertIsNone(request.data)
    def test_catalog_does_not_retry_auth_failure(self):
        from unittest.mock import Mock
        opener=Mock()
        opener.open.side_effect=bridge.urllib.error.HTTPError("https://example.invalid",401,"unauthorized",{},None)
        with patch.dict(os.environ, {"AVELLO_CLAUDE_API_KEY":"fake"}, clear=True):
            with patch.object(bridge.urllib.request,"build_opener",return_value=opener):
                result=bridge.list_models("claude")
                self.assertEqual(result["http_status"],401)
                self.assertEqual(result,bridge.list_models("claude"))
        self.assertEqual(opener.open.call_count,1)
        self.assertNotIn("fake",str(result))
    def test_catalog_filters_unsafe_model_ids(self):
        import io
        from unittest.mock import Mock
        opener=Mock()
        opener.open.return_value=io.BytesIO(b'{"data":[{"id":"valid-model"},{"id":"bad model"}]}')
        with patch.dict(os.environ, {"AVELLO_GPT_API_KEY":"fake"}, clear=True):
            with patch.object(bridge.urllib.request,"build_opener",return_value=opener):
                self.assertEqual(bridge.list_models()["models"],["valid-model"])


class SmokeTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(bridge,"_SMOKE_LEDGER_PATH",str(Path(self.tmp.name)/"ledger.sqlite3"))
        self.path_patch.start()
        self.env_patch = patch.dict(os.environ,{"AVELLO_SMOKE_ENABLED":"true","AVELLO_SMOKE_RUN_ID":"offline-test","AVELLO_GPT_API_KEY":"fake","AVELLO_CLAUDE_API_KEY":"fake","AVELLO_CLAUDE_MODEL":"claude-opus-5","AVELLO_CALLS_ENABLED":"false"},clear=True)
        self.env_patch.start()
        self.executor_patch = patch.object(bridge._SMOKE_EXECUTOR,"submit",side_effect=lambda fn,*args:fn(*args))
        self.executor_patch.start()
    def tearDown(self):
        self.executor_patch.stop(); self.env_patch.stop(); self.path_patch.stop(); self.tmp.cleanup()
    def test_smoke_is_disabled_by_default(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(bridge.smoke_probe()["reason"],"smoke_disabled")
    def test_gpt_smoke_is_persistent_and_bounded(self):
        raw={"model":"gpt-6.1-sol","output":[{"content":[{"type":"output_text","text":"AVELLO_OK"}]}],"usage":{"input_tokens":9,"output_tokens":4}}
        with patch.object(bridge,"_call",return_value=raw) as call:
            self.assertEqual(bridge.smoke_probe()["status"],"accepted")
            self.assertEqual(bridge.smoke_probe()["status"],"ok")
            self.assertEqual(bridge.smoke_probe()["status"],"ok")
        self.assertEqual(call.call_count,1)
        self.assertEqual(call.call_args.args[2]["max_output_tokens"],64)
        self.assertEqual(os.environ["AVELLO_CALLS_ENABLED"],"false")
    def test_both_providers_have_one_slot(self):
        raw={"model":"test","content":[{"type":"text","text":"AVELLO_OK"}],"output":[{"content":[{"type":"output_text","text":"AVELLO_OK"}]}]}
        with patch.object(bridge,"_call",return_value=raw) as call:
            bridge.smoke_probe("gpt");bridge.smoke_probe("claude")
            bridge.smoke_probe("gpt");bridge.smoke_probe("claude")
        self.assertEqual(call.call_count,2)
        self.assertEqual(call.call_args.args[2]["max_tokens"],64)
    def test_error_is_not_retried(self):
        with patch.object(bridge,"_call",return_value={"status":"network_error"}) as call:
            bridge.smoke_probe()
            self.assertEqual(bridge.smoke_probe()["status"],"network_error")
        self.assertEqual(call.call_count,1)
    def test_reserved_unknown_request_is_never_resubmitted(self):
        with patch.object(bridge._SMOKE_EXECUTOR,"submit") as submit:
            bridge.smoke_probe()
            self.assertEqual(bridge.smoke_probe()["status"],"queued_or_unknown")
        self.assertEqual(submit.call_count,1)

if __name__=="__main__": unittest.main()
