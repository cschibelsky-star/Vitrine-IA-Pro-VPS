"""Client for the local allowlisted maintenance broker."""
import json
import socket

TARGET = "vitrine-super-v2-operational-hml-operational_mcp-1"
SCOPES = {"candidate_status": "projects:read", "candidate_restart": "projects:write"}


def authorize(token, operation, subject, enabled, confirm=""):
    if operation not in SCOPES:
        raise PermissionError("operation_not_allowed")
    if token is None or token.subject != subject:
        raise PermissionError("subject_not_authorized")
    if "projects:read" not in token.scopes or SCOPES[operation] not in token.scopes:
        raise PermissionError("scope_required")
    if not enabled:
        raise PermissionError("maintenance_disabled")
    if operation == "candidate_restart" and confirm != "EXECUTAR":
        raise PermissionError("confirmation_required")


def call_maintenance(operation):
    if operation not in SCOPES:
        raise ValueError("operation_not_allowed")
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(60)
        sock.connect("/run/super-v2-maintenance/operations.sock")
        sock.sendall(json.dumps({"operation": operation}).encode() + b"\n")
        with sock.makefile("rb") as stream:
            raw = stream.readline(8193)
    if len(raw) > 8192 or not raw.endswith(b"\n"):
        raise ValueError("invalid_response")
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("maintenance_failed")
    if result.get("operation") != operation or result.get("target") != TARGET:
        raise RuntimeError("response_mismatch")
    return result
