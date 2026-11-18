"""Fail-closed SSH transport for typed, server-side operations.

This module is deliberately NOT an arbitrary command executor. Installation,
credential provisioning, server-side operation scripts and MCP exposure require
separate review and homologation (issue #87 / PR #74).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ALLOWED_OPERATIONS = frozenset({
    "service_health",
    "preserve_docker_image",
    "backup_sqlite_volume",
    "verify_sqlite_backup",
    "deploy_service_commit_hml",
    "rollback_service",
})
PROJECT = "vitrine-avello-private"
SERVICE = "avello_private_mcp"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")


@dataclass(frozen=True)
class SSHExecutorConfig:
    host: str
    user: str
    identity_file: Path
    known_hosts_file: Path
    remote_wrapper: str = "/usr/local/libexec/vitrine-ops-executor"
    timeout_seconds: int = 90


def validate_request(operation: str, project_id: str, service: str,
                     run_id: str, commit_sha: str | None = None) -> None:
    if operation not in ALLOWED_OPERATIONS:
        raise ValueError("operation_not_allowed")
    if project_id != PROJECT or service != SERVICE:
        raise ValueError("scope_not_allowed")
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("invalid_run_id")
    if operation == "deploy_service_commit_hml":
        if not commit_sha or not _SHA.fullmatch(commit_sha):
            raise ValueError("invalid_commit_sha")
    elif commit_sha is not None:
        raise ValueError("unexpected_commit_sha")


def execute(config: SSHExecutorConfig, operation: str, project_id: str,
            service: str, run_id: str, commit_sha: str | None = None) -> str:
    validate_request(operation, project_id, service, run_id, commit_sha)
    if not config.known_hosts_file.is_file() or not config.identity_file.is_file():
        raise RuntimeError("ssh_identity_or_host_key_missing")
    if not config.host or not config.user:
        raise RuntimeError("ssh_target_missing")
    if config.remote_wrapper != "/usr/local/libexec/vitrine-ops-executor":
        raise RuntimeError("unapproved_remote_wrapper")
    # No shell interpolation, no SSH agent fallback, no interactive prompts.
    command = [
        "ssh", "-T", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "ConnectTimeout=10",
        "-o", f"UserKnownHostsFile={config.known_hosts_file}",
        "-i", str(config.identity_file),
        "--", f"{config.user}@{config.host}",
        config.remote_wrapper, operation, project_id, service, run_id,
    ]
    if commit_sha:
        command.append(commit_sha)
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=config.timeout_seconds,
        check=False,
    )
    if result.returncode:
        # Never echo stderr/stdout: remote output could contain sensitive data.
        raise RuntimeError(f"remote_operation_failed:{result.returncode}")
    return result.stdout
