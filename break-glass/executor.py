from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SOCKET_PATH = Path(os.getenv("BREAK_GLASS_EXECUTOR_SOCKET", "/run/break-glass/executor.sock"))
SOCKET_GID = int(os.getenv("BREAK_GLASS_SOCKET_GID", "8871"))
AUDIT_LOG = Path(os.getenv("BREAK_GLASS_EXECUTOR_AUDIT_LOG", "/var/log/vitrine-break-glass/executor-audit.jsonl"))
DATA_DIR = Path(os.getenv("BREAK_GLASS_DATA_DIR", "/var/lib/vitrine-break-glass"))
TOKEN_FILE = Path(os.getenv("BREAK_GLASS_TOKEN_FILE", "/var/lib/vitrine-break-glass/token"))
STATE_FILE = Path(os.getenv("BREAK_GLASS_EXECUTOR_STATE", "/diagnostics/executor-state.json"))
V5_CONTAINER = os.getenv("BREAK_GLASS_V5_CONTAINER", "vitrine_mcp_v5")
MAX_LOG_LINES = int(os.getenv("BREAK_GLASS_MAX_LOG_LINES", "500"))
KNOWN_GOOD_TAG = os.getenv("BREAK_GLASS_KNOWN_GOOD_TAG", "vitrine-mcp-v5:break-glass-known-good")
V5_COMPOSE_FILE = os.getenv("BREAK_GLASS_V5_COMPOSE_FILE", "/srv/connectors/vitrine-vps-mcp/docker-compose.connector-v5.yml")
V5_DOCKER_PROJECT = os.getenv("BREAK_GLASS_V5_DOCKER_PROJECT", "vitrine-mcp-v5-v59")
RELEASE_ID = "v5-current-known-good"


def _state(phase: str, ok: bool = True, error: str = "") -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "phase": phase, "ok": ok, "error": error[:300]}, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass


def _prepare_shared_dirs() -> None:
    for path in (SOCKET_PATH.parent, AUDIT_LOG.parent, DATA_DIR):
        path.mkdir(parents=True, exist_ok=True)
        os.chown(path, -1, SOCKET_GID)
        os.chmod(path, 0o2770)


def _ensure_token() -> None:
    if TOKEN_FILE.is_file() and TOKEN_FILE.stat().st_size > 0:
        os.chown(TOKEN_FILE, -1, SOCKET_GID)
        os.chmod(TOKEN_FILE, 0o640)
        return
    tmp = TOKEN_FILE.with_suffix(".tmp")
    tmp.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
    os.chown(tmp, -1, SOCKET_GID)
    os.chmod(tmp, 0o640)
    os.replace(tmp, TOKEN_FILE)


def _audit(op: str, ok: bool, detail: str = "") -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat(), "component": "break-glass-executor", "operation": op, "ok": ok, "detail": detail[:500]}
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _run(argv: list[str], timeout: int = 30) -> dict:
    proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": proc.stdout[-50000:], "stderr": proc.stderr[-10000:]}


def _inspect_format(fmt: str) -> str:
    result = _run(["docker", "inspect", "--format", fmt, V5_CONTAINER], timeout=15)
    if not result["ok"]:
        raise RuntimeError("v5_inspect_failed")
    return result["stdout"].strip()


def _capture_known_good() -> dict:
    try:
        image_id = _inspect_format("{{.Image}}")
        compose_image = _inspect_format("{{.Config.Image}}")
        if not image_id or not compose_image:
            raise RuntimeError("v5_image_metadata_missing")
        tagged = _run(["docker", "tag", image_id, KNOWN_GOOD_TAG], timeout=20)
        if not tagged["ok"]:
            raise RuntimeError("known_good_tag_failed")
        _audit("capture_known_good", True, f"release_id={RELEASE_ID};compose_image={compose_image}")
        return {"ok": True, "release_id": RELEASE_ID, "compose_image": compose_image}
    except Exception as exc:
        _audit("capture_known_good", False, type(exc).__name__)
        return {"ok": False, "error": "known_good_capture_failed"}


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
        if release_id != RELEASE_ID:
            result = {"ok": False, "error": "release_not_allowed"}
            _audit("rollback", False, release_id)
            return result
        if not V5_COMPOSE_FILE.startswith("/srv/connectors/vitrine-vps-mcp/"):
            result = {"ok": False, "error": "compose_path_blocked"}
            _audit("rollback", False, release_id)
            return result
        if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in V5_DOCKER_PROJECT):
            result = {"ok": False, "error": "docker_project_blocked"}
            _audit("rollback", False, release_id)
            return result
        inspect = _run(["docker", "image", "inspect", KNOWN_GOOD_TAG], timeout=20)
        if not inspect["ok"]:
            result = {"ok": False, "error": "rollback_image_missing"}
            _audit("rollback", False, release_id)
            return result
        try:
            compose_image = _inspect_format("{{.Config.Image}}")
        except Exception:
            result = {"ok": False, "error": "compose_image_unknown"}
            _audit("rollback", False, release_id)
            return result
        tag = _run(["docker", "tag", KNOWN_GOOD_TAG, compose_image], timeout=20)
        if not tag["ok"]:
            result = {"ok": False, "error": "rollback_tag_failed", "stderr": tag.get("stderr", "")}
            _audit("rollback", False, release_id)
            return result
        proc = subprocess.run(["docker", "compose", "-p", V5_DOCKER_PROJECT, "-f", V5_COMPOSE_FILE, "up", "-d", "--no-build", "--force-recreate", "connector_v5"], text=True, capture_output=True, timeout=60, check=False)
        result = {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": proc.stdout[-50000:], "stderr": proc.stderr[-10000:], "release_id": release_id}
        _audit("rollback", result["ok"], release_id)
        return result
    result = {"ok": False, "error": "operation_not_allowed"}
    _audit(str(op), False, "operation_not_allowed")
    return result


def main() -> None:
    _state("starting")
    _prepare_shared_dirs()
    _state("shared_dirs_ready")
    _ensure_token()
    _state("token_ready")
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()
    capture = _capture_known_good()
    _state("known_good_ready" if capture.get("ok") else "known_good_failed", bool(capture.get("ok")), str(capture.get("error", "")))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(SOCKET_PATH))
        os.chown(SOCKET_PATH, -1, SOCKET_GID)
        os.chmod(SOCKET_PATH, 0o660)
        server.listen(8)
        _state("listening")
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
    try:
        main()
    except Exception as exc:
        _state("crashed", False, f"{type(exc).__name__}:{exc}")
        raise
