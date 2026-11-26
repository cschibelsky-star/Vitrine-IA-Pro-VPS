"""Private Unix socket bridge for controlled host operations."""
import json
import os
import socketserver
from pathlib import Path
from host_operations import execute

SOCKET = Path("/run/super-v2-host/operations.sock")

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(20)
        try:
            raw = self.rfile.readline(4097)

            if len(raw) > 4096 or not raw.endswith(b"\n"):
                raise ValueError("invalid_request")

            data = json.loads(raw)

            if not isinstance(data, dict):
                raise ValueError("invalid_request")

            if set(data) != {"project", "operation"}:
                raise ValueError("invalid_fields")

            if not all(isinstance(v, str) for v in data.values()):
                raise ValueError("invalid_values")

            result = execute(
                data["project"],
                data["operation"]
            )

        except Exception:
            result = {
                "ok": False,
                "error": "operation_denied_or_failed"
            }

        self.wfile.write(
            json.dumps(result).encode() + b"\n"
        )

if __name__ == "__main__":
    os.umask(0o077)
    SOCKET.parent.mkdir(mode=0o700, exist_ok=True)

    if SOCKET.parent.is_symlink():
        raise RuntimeError("invalid_socket_directory")

    if SOCKET.parent.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_socket_permissions")

    if SOCKET.exists() or SOCKET.is_symlink():
        raise RuntimeError("socket_already_exists")

    with socketserver.UnixStreamServer(
        str(SOCKET), Handler
    ) as server:
        try:
            server.serve_forever()
        finally:
            SOCKET.unlink(missing_ok=True)
