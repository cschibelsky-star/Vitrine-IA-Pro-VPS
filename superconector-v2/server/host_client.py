"""Private client for the native host executor."""
import json
import socket

OPERATIONS = frozenset((
    "git_status",
    "git_revision",
    "git_history",
    "git_diff_check",
))

def call_host(project, operation):
    if project != "superconector-v2":
        raise ValueError("project_not_allowed")

    if operation not in OPERATIONS:
        raise ValueError("operation_not_allowed")

    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(20)
        s.connect("/run/super-v2-host/operations.sock")

        payload = {
            "project": project,
            "operation": operation,
        }

        s.sendall(json.dumps(payload).encode() + b"\n")

        with s.makefile("rb") as stream:
            raw = stream.readline(65537)

        if len(raw) > 65536 or not raw.endswith(b"\n"):
            raise ValueError("invalid_host_response")

        result = json.loads(raw)

        if not isinstance(result, dict):
            raise ValueError("invalid_host_response")

        if result.get("ok") is not True:
            raise ValueError("host_operation_failed")

        if result.get("project") != project:
            raise ValueError("project_mismatch")

        if result.get("operation") != operation:
            raise ValueError("operation_mismatch")

        return result
