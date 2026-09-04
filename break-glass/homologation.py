from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:8871"
V5_HOST = "127.0.0.1"
V5_PORT = 8867
TOKEN_FILE = Path("/var/lib/vitrine-break-glass/token")
RESULT_FILE = Path("/results/homologation-result.json")
RELEASE_ID = "v5-current-known-good"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist(result: dict) -> None:
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    snapshot = dict(result)
    snapshot["updated_at"] = now()
    RESULT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request(path: str, method: str = "GET", token: str | None = None, body: dict | None = None, timeout: int = 25) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"raw": raw[:500]}
        return exc.code, payload
    except Exception as exc:
        return 599, {"ok": False, "error": f"transport_{type(exc).__name__}"}


def wait_v5(timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((V5_HOST, V5_PORT), timeout=3):
                return True
        except OSError:
            time.sleep(2)
    return False


def main() -> None:
    result: dict = {"started_at": now(), "checks": {}}
    persist(result)

    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception as exc:
        result["checks"]["token_read"] = {"ok": False, "error": type(exc).__name__}
        result["ok"] = False
        result["finished_at"] = now()
        persist(result)
        raise SystemExit(1)

    status, payload = request("/health")
    result["checks"]["health"] = {"ok": status == 200 and payload.get("ok") is True, "status": status, "error": payload.get("error")}
    persist(result)

    status, payload = request("/v1/v5/logs?lines=5")
    result["checks"]["auth_denied"] = {"ok": status == 401, "status": status, "error": payload.get("error")}
    persist(result)

    status, payload = request("/v1/v5/logs?lines=5", token=token)
    result["checks"]["logs"] = {
        "ok": status == 200 and payload.get("ok") is True,
        "status": status,
        "exit_code": payload.get("exit_code"),
        "stdout_chars": len(str(payload.get("stdout") or "")),
        "error": payload.get("error"),
    }
    persist(result)

    status, payload = request("/v1/v5/restart", method="POST", token=token, timeout=35)
    restart_api_ok = status == 200 and payload.get("ok") is True
    restart_health_ok = wait_v5()
    result["checks"]["restart"] = {
        "ok": restart_api_ok and restart_health_ok,
        "status": status,
        "api_ok": restart_api_ok,
        "v5_recovered": restart_health_ok,
        "exit_code": payload.get("exit_code"),
        "error": payload.get("error"),
    }
    persist(result)

    if restart_health_ok:
        status, payload = request("/v1/v5/rollback", method="POST", token=token, body={"release_id": RELEASE_ID}, timeout=70)
        rollback_api_ok = status == 200 and payload.get("ok") is True
        rollback_health_ok = wait_v5()
        result["checks"]["rollback"] = {
            "ok": rollback_api_ok and rollback_health_ok,
            "status": status,
            "api_ok": rollback_api_ok,
            "v5_recovered": rollback_health_ok,
            "exit_code": payload.get("exit_code"),
            "error": payload.get("error"),
        }
    else:
        result["checks"]["rollback"] = {"ok": False, "skipped": True, "reason": "restart_health_failed"}
    persist(result)

    result["finished_at"] = now()
    result["ok"] = all(check.get("ok") is True for check in result["checks"].values())
    persist(result)
    print(json.dumps({"ok": result["ok"], "checks": {k: v.get("ok") for k, v in result["checks"].items()}}, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
