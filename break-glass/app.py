from __future__ import annotations

import hmac
import json
import os
import socket
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = os.getenv("BREAK_GLASS_HOST", "0.0.0.0")
PORT = int(os.getenv("BREAK_GLASS_PORT", "8099"))
TOKEN_FILE = Path(os.getenv("BREAK_GLASS_TOKEN_FILE", "/var/lib/vitrine-break-glass/token"))
SOCKET_PATH = os.getenv("BREAK_GLASS_EXECUTOR_SOCKET", "/run/break-glass/executor.sock")
AUDIT_LOG = Path(os.getenv("BREAK_GLASS_AUDIT_LOG", "/var/log/vitrine-break-glass/audit.jsonl"))
MAX_LOG_LINES = int(os.getenv("BREAK_GLASS_MAX_LOG_LINES", "500"))
RATE_WINDOW_SECONDS = int(os.getenv("BREAK_GLASS_RATE_WINDOW", "60"))
RATE_MAX_REQUESTS = int(os.getenv("BREAK_GLASS_RATE_MAX", "20"))
_REQUESTS: dict[str, list[float]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(action: str, client: str, ok: bool, detail: str = "") -> None:
    record = {"at": _now(), "component": "break-glass-api", "action": action, "client": client, "ok": ok, "detail": detail[:500]}
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_token() -> str:
    env_token = os.getenv("BREAK_GLASS_TOKEN", "").strip()
    if env_token:
        return env_token
    if not TOKEN_FILE.is_file():
        raise RuntimeError("break_glass_token_missing")
    value = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("break_glass_token_empty")
    return value


TOKEN = _load_token()


def _authorized(value: str | None) -> bool:
    if not value or not value.startswith("Bearer "):
        return False
    return hmac.compare_digest(value[7:].encode(), TOKEN.encode())


def _rate_allowed(client: str) -> bool:
    now = time.time()
    current = [t for t in _REQUESTS.get(client, []) if now - t < RATE_WINDOW_SECONDS]
    if len(current) >= RATE_MAX_REQUESTS:
        _REQUESTS[client] = current
        return False
    current.append(now)
    _REQUESTS[client] = current
    return True


def _executor(payload: dict) -> dict:
    raw = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(20)
        sock.connect(SOCKET_PATH)
        sock.sendall(raw)
        chunks = []
        while True:
            part = sock.recv(65536)
            if not part:
                break
            chunks.append(part)
            if b"\n" in part:
                break
    return json.loads(b"".join(chunks).decode().strip())


class Handler(BaseHTTPRequestHandler):
    server_version = "VitrineBreakGlass/0.1"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _client(self) -> str:
        return self.client_address[0]

    def _guard(self, action: str) -> bool:
        client = self._client()
        if not _rate_allowed(client):
            _audit(action, client, False, "rate_limited")
            self._send(429, {"ok": False, "error": "rate_limited"})
            return False
        if not _authorized(self.headers.get("Authorization")):
            _audit(action, client, False, "unauthorized")
            self._send(401, {"ok": False, "error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"ok": True, "service": "vitrine-break-glass", "version": "0.1"})
            return
        if parsed.path == "/v1/v5/logs":
            if not self._guard("logs"):
                return
            try:
                lines = int(parse_qs(parsed.query).get("lines", ["100"])[0])
            except ValueError:
                lines = 100
            lines = min(max(lines, 1), MAX_LOG_LINES)
            try:
                result = _executor({"op": "logs", "lines": lines})
                _audit("logs", self._client(), bool(result.get("ok")), f"lines={lines}")
                self._send(200 if result.get("ok") else 502, result)
            except Exception as exc:
                _audit("logs", self._client(), False, type(exc).__name__)
                self._send(502, {"ok": False, "error": "executor_unavailable"})
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/v1/v5/restart":
            if not self._guard("restart"):
                return
            payload = {"op": "restart"}
            action = "restart"
        elif parsed.path == "/v1/v5/rollback":
            if not self._guard("rollback"):
                return
            length = min(int(self.headers.get("Content-Length", "0") or 0), 4096)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send(400, {"ok": False, "error": "invalid_json"})
                return
            release_id = str(body.get("release_id", "")).strip()
            if not release_id or len(release_id) > 80 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in release_id):
                self._send(400, {"ok": False, "error": "invalid_release_id"})
                return
            payload = {"op": "rollback", "release_id": release_id}
            action = "rollback"
        else:
            self._send(404, {"ok": False, "error": "not_found"})
            return
        try:
            result = _executor(payload)
            _audit(action, self._client(), bool(result.get("ok")), str(result.get("error", "")))
            self._send(200 if result.get("ok") else 409, result)
        except Exception as exc:
            _audit(action, self._client(), False, type(exc).__name__)
            self._send(502, {"ok": False, "error": "executor_unavailable"})

    def log_message(self, fmt: str, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
