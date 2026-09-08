from __future__ import annotations

import os
import subprocess
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
    if op != "health" and confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    proc = subprocess.run(
        ALLOWED[op],
        cwd=str(Path("/")),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "operation": op,
        "candidate": CANDIDATE,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-20000:],
        "stderr": proc.stderr[-8000:],
    }
