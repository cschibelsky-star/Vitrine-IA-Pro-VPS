from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:8871"
TOKEN_FILE = Path("/var/lib/vitrine-break-glass/token")
RESULT_FILE = Path("/results/rollback-diagnostic.json")
RELEASE_ID = "v5-current-known-good"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def v5_tcp_ok() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8867), timeout=3):
            return True
    except OSError:
        return False


def main() -> None:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    body = json.dumps({"release_id": RELEASE_ID}).encode()
    request = urllib.request.Request(
        BASE + "/v1/v5/rollback",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    status = 599
    payload: dict = {}
    try:
        with urllib.request.urlopen(request, timeout=70) as response:
            status = response.status
            payload = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode()
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"raw": raw[:1000]}
    except Exception as exc:
        payload = {"ok": False, "error": f"transport_{type(exc).__name__}"}

    result = {
        "at": now(),
        "status": status,
        "ok": status == 200 and payload.get("ok") is True,
        "api_ok": payload.get("ok"),
        "error": payload.get("error"),
        "exit_code": payload.get("exit_code"),
        "stdout_tail": str(payload.get("stdout") or "")[-2000:],
        "stderr_tail": str(payload.get("stderr") or "")[-2000:],
        "release_id": payload.get("release_id"),
        "v5_tcp_ok": v5_tcp_ok(),
    }
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["ok"], "status": status, "exit_code": result["exit_code"], "v5_tcp_ok": result["v5_tcp_ok"]}, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
