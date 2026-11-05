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

if __name__=="__main__": unittest.main()
