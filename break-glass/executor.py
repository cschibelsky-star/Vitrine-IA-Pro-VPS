from __future__ import annotations

import json
import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SOCKET_PATH = Path(os.getenv("BREAK_GLASS_EXECUTOR_SOCKET", "/run/break-glass/executor.sock"))
SOCKET_GID = int(os.getenv("BREAK_GLASS_SOCKET_GID", "8871"))
AUDIT_LOG = Path(os.getenv("BREAK_GLASS_EXECUTOR_AUDIT_LOG", "/var/log/vitrine-break-glass/executor-audit.jsonl"))
V5_CONTAINER = os.getenv("BREAK_GLASS_V5_CONTAINER", "vitrine_mcp_v5")
RELEASES_FILE = Path(os.getenv("BREAK_GLASS_RELEASES_FILE", "/etc/vitrine-break-glass/releases.json"))
MAX_LOG_LINES = int(os.getenv("BREAK_GLASS_MAX_LOG_LINES", "500"))


def _audit(op: str, ok: bool, detail: str = "") -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat(), "component": "break-glass-executor", "operation": op, "ok": ok, "detail": detail[:500]}
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _run(argv: list[str], timeout: int = 30) -> dict:
    proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": proc.stdout[-50000:], "stderr": proc.stderr[-10000:]}


def _releases() -> dict[str, dict]:
    if not RELEASES_FILE.is_file():
        return {}
    data = json.loads(RELEASES_FILE.read_text(encoding="utf-8"))
    entries = data.get("releases", {})
    return entries if isinstance(entries, dict) else {}


def _handle(request: dict) -> dict:
    op = request.get("op")
    if op == "logs":
        try:
            lines = min(max(int(request.get("lines", 100)), 1), MAX_LOG_LINES)
        except (TypeError, ValueError):
            lines = 100
        result = _run(["docker", "logs", "--tail", str(lines), V5_CONTAINER], timeout=15)
        _audit("logs", result["ok"], f"lines={lines}")
        return result

    if op == "restart":
        result = _run(["docker", "restart", "--time", "10", V5_CONTAINER], timeout=30)
        _audit("restart", result["ok"], result.get("stderr", ""))
        return result

    if op == "rollback":
        release_id = str(request.get("release_id", ""))
        release = _releases().get(release_id)
        if not isinstance(release, dict):
            result = {"ok": False, "error": "release_not_allowed"}
            _audit("rollback", False, release_id)
            return result

        image = str(release.get("image", "")).strip()
        compose_image = str(release.get("compose_image", "")).strip()
        compose_file = str(release.get("compose_file", "")).strip()
        docker_project = str(release.get("docker_project", "")).strip()
        if not image or not compose_image or not compose_file or not docker_project:
            result = {"ok": False, "error": "release_definition_invalid"}
            _audit("rollback", False, release_id)
            return result
        if not compose_file.startswith("/srv/connectors/vitrine-vps-mcp/"):
            result = {"ok": False, "error": "compose_path_blocked"}
            _audit("rollback", False, release_id)
            return result
        if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in docker_project):
            result = {"ok": False, "error": "docker_project_blocked"}
            _audit("rollback", False, release_id)
            return result

        inspect = _run(["docker", "image", "inspect", image], timeout=20)
        if not inspect["ok"]:
            result = {"ok": False, "error": "rollback_image_missing"}
            _audit("rollback", False, release_id)
            return result

        tag = _run(["docker", "tag", image, compose_image], timeout=20)
        if not tag["ok"]:
            result = {"ok": False, "error": "rollback_tag_failed", "stderr": tag.get("stderr", "")}
            _audit("rollback", False, release_id)
            return result

        proc = subprocess.run(
            ["docker", "compose", "-p", docker_project, "-f", compose_file, "up", "-d", "--no-build", "--force-recreate", "connector_v5"],
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        result = {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": proc.stdout[-50000:], "stderr": proc.stderr[-10000:], "release_id": release_id}
        _audit("rollback", result["ok"], release_id)
        return result

    result = {"ok": False, "error": "operation_not_allowed"}
    _audit(str(op), False, "operation_not_allowed")
    return result


def main() -> None:
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(SOCKET_PATH))
        os.chown(SOCKET_PATH, -1, SOCKET_GID)
        os.chmod(SOCKET_PATH, 0o660)
        server.listen(8)
        while True:
            conn, _ = server.accept()
            with conn:
                raw = b""
                while b"\n" not in raw and len(raw) <= 8192:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    raw += chunk
                try:
                    request = json.loads(raw.decode().split("\n", 1)[0])
                    if not isinstance(request, dict):
                        raise ValueError("request_not_object")
                    result = _handle(request)
                except Exception as exc:
                    result = {"ok": False, "error": type(exc).__name__}
                    _audit("invalid_request", False, type(exc).__name__)
                conn.sendall((json.dumps(result, ensure_ascii=False) + "\n").encode())


if __name__ == "__main__":
    main()
