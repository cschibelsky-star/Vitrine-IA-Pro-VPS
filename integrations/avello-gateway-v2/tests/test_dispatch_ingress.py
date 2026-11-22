"""ASGI ingress tests without MCP dependency or external network."""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth_guard import ProtectedMCP, _approval_from_headers
from dispatch_request_context import current_approval


class GuardTests(unittest.TestCase):
    def test_missing_and_duplicate_approval_headers_fail_closed(self):
        self.assertIsNone(_approval_from_headers([]))
        headers = [(b"x-via-identity", b"alice")] * 2
        self.assertIsNone(_approval_from_headers(headers))

    def test_request_context_does_not_leak(self):
        captured = []
        async def inner(scope, receive, send):
            captured.append(current_approval.get())
        async def invoke(headers):
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(message):
                captured.append(message)
            await ProtectedMCP(inner)({"type": "http", "headers": headers}, receive, send)
        with patch.dict(os.environ, {"AVELLO_V2_MCP_BEARER_TOKEN": "test-bearer"}):
            headers = [(b"authorization", b"Bearer test-bearer"),
                       (b"x-via-identity", b"alice"),
                       (b"x-via-approval-nonce", b"a"*32),
                       (b"x-via-approval-timestamp", b"1700000000"),
                       (b"x-via-approval-signature", b"b"*64)]
            asyncio.run(invoke(headers))
            self.assertEqual(captured[0].identity, "alice")
            self.assertIsNone(current_approval.get())
            asyncio.run(invoke([(b"authorization", b"Bearer test-bearer")]))
            self.assertIsNone(captured[-1])

    def test_unauthenticated_cannot_reach_inner(self):
        called = []
        async def inner(scope, receive, send):
            called.append(True)
        async def run():
            sent = []
            async def receive():
                return {}
            async def send(message):
                sent.append(message)
            await ProtectedMCP(inner)({"type": "http", "headers": []}, receive, send)
            return sent
        with patch.dict(os.environ, {"AVELLO_V2_MCP_BEARER_TOKEN": "test-bearer"}):
            messages = asyncio.run(run())
        self.assertFalse(called)
        self.assertEqual(messages[0]["status"], 401)


if __name__ == "__main__":
    unittest.main()
