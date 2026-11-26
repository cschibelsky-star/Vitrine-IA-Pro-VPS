"""Controlled host operations for Superconector V2."""
import subprocess
import time
from pathlib import Path

PROJECTS = {
    "superconector-v2": Path(
        "/srv/projects/super-v2-operational-dev"
    )
}

OPERATIONS = {
    "git_status": (
        "git", "--no-optional-locks",
        "status", "--short", "--branch"
    ),
    "git_revision": (
        "git", "rev-parse", "HEAD"
    ),
    "git_history": (
        "git", "log", "-5", "--oneline"
    ),
    "git_diff_check": (
        "git", "diff", "--check"
    ),
}

def execute(project, operation):
    if project not in PROJECTS:
        raise ValueError("project_not_allowed")

    if operation not in OPERATIONS:
        raise ValueError("operation_not_allowed")

    root = PROJECTS[project].resolve(strict=True)
    started = time.monotonic()

    result = subprocess.run(
        (
            "/usr/bin/git",
            "-c", "safe.directory=" + str(root),
            "-c", "core.fsmonitor=false",
            "-c", "core.hooksPath=/dev/null",
            *OPERATIONS[operation][1:],
        ),
        cwd=root,
        shell=False,
        capture_output=True,
        text=True,
        timeout=15,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )

    return {
        "ok": result.returncode == 0,
        "project": project,
        "operation": operation,
        "exit_code": result.returncode,
        "stdout": result.stdout[:8192],
        "stderr": result.stderr[:4096],
        "duration_ms": int(
            (time.monotonic() - started) * 1000
        ),
    }
