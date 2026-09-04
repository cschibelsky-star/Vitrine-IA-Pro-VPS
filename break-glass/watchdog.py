from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

WATCH_HOST = os.getenv("BREAK_GLASS_WATCH_HOST", "127.0.0.1")
WATCH_PORT = int(os.getenv("BREAK_GLASS_WATCH_PORT", "8867"))
SOCKET_PATH = os.getenv("BREAK_GLASS_EXECUTOR_SOCKET", "/run/break-glass/executor.sock")
STATE_FILE = Path(os.getenv("BREAK_GLASS_WATCH_STATE", "/var/lib/vitrine-break-glass/watchdog.json"))
AUDIT_LOG = Path(os.getenv("BREAK_GLASS_WATCH_AUDIT", "/var/log/vitrine-break-glass/watchdog.jsonl"))
FAIL_THRESHOLD = int(os.getenv("BREAK_GLASS_FAIL_THRESHOLD", "3"))
INTERVAL = int(os.getenv("BREAK_GLASS_WATCH_INTERVAL", "30"))
COOLDOWN = int(os.getenv("BREAK_GLASS_COOLDOWN", "300"))
ROLLBACK_RELEASE = os.getenv("BREAK_GLASS_AUTO_ROLLBACK_RELEASE", "").strip()


def _audit(action: str, detail: str = "") -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "component": "break-glass-watchdog", "action": action, "detail": detail[:500]}, ensure_ascii=False) + "\n")


def _load() -> dict:
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"failures": 0, "last_action_at": 0, "restart_attempted": False}


def _save(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _healthy() -> bool:
    try:
        with socket.create_connection((WATCH_HOST, WATCH_PORT), timeout=3):
            return True
    except OSError:
        return False


def _executor(payload: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(30)
        sock.connect(SOCKET_PATH)
        sock.sendall((json.dumps(payload) + "\n").encode())
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode().strip())


def main() -> None:
    state = _load()
    while True:
        now = int(time.time())
        if _healthy():
            if state.get("failures"):
                _audit("recovered", f"after_failures={state.get('failures')}")
            state = {"failures": 0, "last_action_at": state.get("last_action_at", 0), "restart_attempted": False}
            _save(state)
            time.sleep(INTERVAL)
            continue

        state["failures"] = int(state.get("failures", 0)) + 1
        _audit("probe_failed", f"count={state['failures']}")
        if state["failures"] < FAIL_THRESHOLD:
            _save(state)
            time.sleep(INTERVAL)
            continue

        if now - int(state.get("last_action_at", 0)) < COOLDOWN:
            _audit("cooldown_active")
            _save(state)
            time.sleep(INTERVAL)
            continue

        if not state.get("restart_attempted"):
            result = _executor({"op": "restart"})
            state["restart_attempted"] = True
            state["last_action_at"] = now
            _audit("automatic_restart", json.dumps({"ok": result.get("ok"), "error": result.get("error")}, ensure_ascii=False))
        elif ROLLBACK_RELEASE:
            result = _executor({"op": "rollback", "release_id": ROLLBACK_RELEASE})
            state["last_action_at"] = now
            _audit("automatic_rollback", json.dumps({"release_id": ROLLBACK_RELEASE, "ok": result.get("ok"), "error": result.get("error")}, ensure_ascii=False))
        else:
            _audit("rollback_not_configured")
            state["last_action_at"] = now

        _save(state)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
