import unittest
from unittest.mock import patch
from redis_probe import redis_ping

class Socket:
    def __init__(self, reply):
        self.reply = reply
        self.sent = None
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def settimeout(self, timeout): pass
    def sendall(self, request): self.sent = request
    def recv(self, n): return self.reply

class RedisProbeTests(unittest.TestCase):
    @patch("redis_probe.socket.create_connection")
    def test_core_pong(self, connect):
        connect.return_value = Socket(b"+PONG\r\n")
        self.assertEqual(redis_ping("core")["status"], "healthy")
        connect.assert_called_once_with(("vitrine_redis", 6379), timeout=2.0)
    @patch("redis_probe.socket.create_connection")
    def test_automation_pong(self, connect):
        connect.return_value = Socket(b"+PONG\r\n")
        self.assertTrue(redis_ping("automation")["ok"])
        connect.assert_called_once_with(("redis", 6379), timeout=2.0)
    @patch("redis_probe.socket.create_connection")
    def test_invalid_target_rejected(self, connect):
        self.assertEqual(redis_ping("localhost")["status"], "target_not_allowed")
        connect.assert_not_called()
    @patch("redis_probe.socket.create_connection")
    def test_auth_required(self, connect):
        connect.return_value = Socket(b"-NOAUTH Authentication required.\r\n")
        result = redis_ping("core")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "authentication_required")
    @patch("redis_probe.socket.create_connection", side_effect=TimeoutError("internal details"))
    def test_timeout_sanitized(self, connect):
        self.assertEqual(redis_ping("core")["status"], "unreachable")
    @patch("redis_probe.socket.create_connection")
    def test_unexpected_reply(self, connect):
        connect.return_value = Socket(b"-ERR something sensitive\r\n")
        self.assertEqual(redis_ping("core")["status"], "unexpected_response")

if __name__ == "__main__":
    unittest.main()
