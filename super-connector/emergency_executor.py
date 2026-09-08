from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

ALLOWED = {
    "health": ["docker", "ps", "--filter", "name=vitrine_super_connector"],
    "logs": ["docker", "logs", "--tail", "200", "vitrine_super_connector"],
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
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-20000:],
        "stderr": proc.stderr[-8000:],
    }
