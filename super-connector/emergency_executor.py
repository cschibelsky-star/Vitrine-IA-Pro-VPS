from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

CANDIDATE = os.getenv("SUPER_CANDIDATE_CONTAINER", "vitrine_super_connector_candidate").strip()
if not CANDIDATE or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in CANDIDATE):
    raise RuntimeError("invalid_candidate_container")

ALLOWED = {
    "health": ["docker", "inspect", "--format", "{{json .State}}", CANDIDATE],
    "logs": ["docker", "logs", "--tail", "200", CANDIDATE],
    "stop": ["docker", "stop", "--time", "20", CANDIDATE],
    "start": ["docker", "start", CANDIDATE],
}


def run(operation: str, confirm: str = "") -> dict[str, Any]:
    op = str(operation or "").strip().lower()
    if op not in ALLOWED:
        return {"ok": False, "error": "operation_not_allowed", "allowed": sorted(ALLOWED)}
    if op not in {"health", "logs"} and confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}

    try:
        proc = subprocess.run(
            ALLOWED[op],
            cwd=str(Path("/")),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "operation": op, "candidate": CANDIDATE}
    except OSError as exc:
        return {"ok": False, "error": type(exc).__name__, "operation": op, "candidate": CANDIDATE}

    return {
        "ok": proc.returncode == 0,
        "operation": op,
        "candidate": CANDIDATE,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-20000:],
        "stderr": proc.stderr[-8000:],
    }


def main() -> int:
    operation = sys.argv[1] if len(sys.argv) > 1 else "health"
    confirm = sys.argv[2] if len(sys.argv) > 2 else ""
    result = run(operation, confirm)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
