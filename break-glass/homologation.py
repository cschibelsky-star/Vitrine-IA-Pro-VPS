from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:8871"
V5_HEALTH = "http://127.0.0.1:8867/"
TOKEN_FILE = Path("/var/lib/vitrine-break-glass/token")
RESULT_FILE = Path("/results/homologation-result.json")
RELEASE_ID = "v5-current-known-good"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def request(path: str, method: str = "GET", token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"raw": raw[:500]}
        return exc.code, payload


def wait_v5(timeout: int = 45) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(V5_HEALTH, timeout=3) as response:
                if response.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def main() -> None:
    result: dict = {"started_at": now(), "checks": {}}
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()

    status, payload = request("/health")
    result["checks"]["health"] = {"ok": status == 200 and payload.get("ok") is True, "status": status}

    status, payload = request("/v1/v5/logs?lines=5")
    result["checks"]["auth_denied"] = {"ok": status == 401, "status": status, "error": payload.get("error")}

    status, payload = request("/v1/v5/logs?lines=5", token=token)
    result["checks"]["logs"] = {
        "ok": status == 200 and payload.get("ok") is True,
        "status": status,
        "exit_code": payload.get("exit_code"),
        "stdout_chars": len(str(payload.get("stdout") or "")),
    }

    status, payload = request("/v1/v5/restart", method="POST", token=token)
    restart_api_ok = status == 200 and payload.get("ok") is True
    restart_health_ok = wait_v5()
    result["checks"]["restart"] = {
        "ok": restart_api_ok and restart_health_ok,
        "status": status,
        "api_ok": restart_api_ok,
        "v5_recovered": restart_health_ok,
        "exit_code": payload.get("exit_code"),
    }

    if restart_health_ok:
        status, payload = request("/v1/v5/rollback", method="POST", token=token, body={"release_id": RELEASE_ID})
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

    result["finished_at"] = now()
    result["ok"] = all(check.get("ok") is True for check in result["checks"].values())
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["ok"], "checks": {k: v.get("ok") for k, v in result["checks"].items()}}, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
