"""ASGI authorization tests: no external service, no credential disclosure."""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import ProtectedMCP


class AuthGuardTests(unittest.TestCase):
    def run_request(self, token, headers=(), scope_type="http"):
        called = []
        messages = []

        async def downstream(scope, receive, send):
            called.append(True)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        with patch.dict(os.environ, {"AVELLO_V2_MCP_BEARER_TOKEN": token} if token else {}, clear=True):
            asyncio.run(ProtectedMCP(downstream)(
                {"type": scope_type, "headers": list(headers)}, receive, send))
        return called, messages

    def test_missing_server_token_fails_closed(self):
        called, messages = self.run_request("", [(b"authorization", b"Bearer anything")])
        self.assertFalse(called)
        self.assertEqual(messages[0]["status"], 401)

    def test_wrong_token_denied(self):
        called, messages = self.run_request("private-placeholder", [(b"authorization", b"Bearer wrong")])
        self.assertFalse(called)
        self.assertEqual(messages[0]["status"], 401)

    def test_duplicate_authorization_denied(self):
        header = (b"authorization", b"Bearer private-placeholder")
        called, messages = self.run_request("private-placeholder", [header, header])
        self.assertFalse(called)
        self.assertEqual(messages[0]["status"], 401)

    def test_correct_token_reaches_downstream(self):
        called, messages = self.run_request(
            "private-placeholder", [(b"authorization", b"Bearer private-placeholder")])
        self.assertEqual(called, [True])
        self.assertEqual(messages, [])

    def test_websocket_denied(self):
        called, messages = self.run_request("private-placeholder", scope_type="websocket")
        self.assertFalse(called)
        self.assertEqual(messages[0]["code"], 1008)


if __name__ == "__main__":
    unittest.main()
