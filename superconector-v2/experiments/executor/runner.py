"""Experimental executor core with a fixed, non-privileged test catalog.

THIS IS NOT AN MCP TOOL AND IS NOT DEPLOYED. It must run only in a disposable
Linux CI sandbox. The caller never supplies commands, paths, credentials or
environment variables. This library is NOT an OS-level isolation boundary.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROFILES = {
    "probe": (sys.executable, "-B", "-c", "print('vitrine_executor_probe_ok')"),
    "syntax": (
        sys.executable, "-B", "-c",
        "import ast,pathlib; ast.parse(pathlib.Path('main.py').read_text(encoding='utf-8')); "
        "ast.parse(pathlib.Path('gateway.py').read_text(encoding='utf-8')); "
        "print('vitrine_executor_syntax_ok')",
    ),
}
MAX_OUTPUT = 4096
TIMEOUT = 10
AUTH_MARKER = "isolated-ci-only"
HEX40 = re.compile(r"^[a-f0-9]{40}$")


def blocked(reason: str, profile: str = "") -> dict[str, Any]:
    return {
        "ok": False, "status": "blocked", "reason": reason, "profile": profile,
        "exit_code": None, "stdout": "", "stderr": "",
        "duration_ms": 0, "dispatch_allowed": False, "production_allowed": False,
    }


def run_profile(
    profile: str,
    server_root: str | Path,
    *,
    approval: str,
    context: str,
    source_sha: str,
    runner=subprocess.run,
) -> dict[str, Any]:
    """Execute one static test profile; no shell, no arbitrary argv or paths.

    The CI-only marker is not an authorization primitive for production.
    An eventual server MUST enforce authentication, immutable workspace,
    namespace/cgroup/network restrictions, and policy BEFORE calling this.
    """
    if not isinstance(profile, str) or profile not in PROFILES:
        return blocked("profile_not_allowed")
    if approval != "EXECUTAR" or context != AUTH_MARKER:
        return blocked("authorization_or_context_missing", profile)
    if not isinstance(source_sha, str) or HEX40.fullmatch(source_sha) is None:
        return blocked("source_sha_invalid", profile)
    try:
        root = Path(server_root).resolve(strict=True)
        if not root.is_dir() or root.is_symlink():
            return blocked("workspace_invalid", profile)
        # This guard prevents passing an arbitrary directory to this test.
        for filename in ("main.py", "gateway.py"):
            item = root / filename
            if not item.is_file() or item.is_symlink() or item.resolve().parent != root:
                return blocked("workspace_files_missing_or_symlinked", profile)
        command = list(PROFILES[profile])
        before = time.monotonic()
        process = runner(
            command, cwd=str(root), shell=False, check=False,
            capture_output=True, text=True, timeout=TIMEOUT,
            env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONNOUSERSITE": "1", "LC_ALL": "C"},
        )
        elapsed = max(0, int((time.monotonic() - before) * 1000))
        out = (process.stdout or "")[:MAX_OUTPUT]
        err = (process.stderr or "")[:MAX_OUTPUT]
        ok = process.returncode == 0
        return {
            "ok": ok, "status": "passed" if ok else "failed",
            "profile": profile, "source_sha": source_sha,
            "exit_code": process.returncode, "stdout": out,
            "stderr": err, "duration_ms": elapsed,
            "output_truncated": len(process.stdout or "") > MAX_OUTPUT or
                                len(process.stderr or "") > MAX_OUTPUT,
            "dispatch_allowed": False, "production_allowed": False,
        }
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return blocked("runner_failed_or_timed_out", profile)
