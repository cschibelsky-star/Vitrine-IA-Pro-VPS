"""Client for the local allowlisted maintenance broker."""
import json
import socket

TARGET = "vitrine-super-v2-operational-hml-operational_mcp-1"
SCOPES = {"candidate_status": "projects:read", "candidate_restart": "projects:write",
          "assessor_hml_snapshot": "projects:write", "project_hml_snapshot": "projects:write",
          "hml_project_catalog": "projects:read", "project_hml_database_backup": "projects:write",
          "project_hml_release_preflight": "projects:read"}
PROJECT_OPERATIONS = {"project_hml_snapshot", "project_hml_database_backup", "project_hml_release_preflight"}
SNAPSHOT_TARGET = "assessor-online-pr137-current-hml"


def authorize(token, operation, subject, enabled, confirm=""):
    if operation not in SCOPES:
        raise PermissionError("operation_not_allowed")
    if token is None or token.subject != subject:
        raise PermissionError("subject_not_authorized")
    if "projects:read" not in token.scopes or SCOPES[operation] not in token.scopes:
        raise PermissionError("scope_required")
    if not enabled:
        raise PermissionError("maintenance_disabled")
    if SCOPES[operation] == "projects:write" and confirm != "EXECUTAR":
        raise PermissionError("confirmation_required")


def call_maintenance(operation, project_id=None, commit=None):
    if operation not in SCOPES:
        raise ValueError("operation_not_allowed")
    if (operation in PROJECT_OPERATIONS) != (project_id is not None):
        raise ValueError("invalid_project_argument")
    payload = {"operation": operation}
    if project_id is not None:
        payload["project_id"] = project_id
    if (operation == "project_hml_release_preflight") != (commit is not None):
        raise ValueError("invalid_commit_argument")
    if commit is not None:
        payload["commit"] = commit
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(60)
        sock.connect("/run/super-v2-maintenance/operations.sock")
        sock.sendall(json.dumps(payload).encode() + b"\n")
        with sock.makefile("rb") as stream:
            raw = stream.readline(8193)
    if len(raw) > 8192 or not raw.endswith(b"\n"):
        raise ValueError("invalid_response")
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("maintenance_failed")
    target = SNAPSHOT_TARGET if operation == "assessor_hml_snapshot" else TARGET
    if operation in PROJECT_OPERATIONS:
        target = project_id
    elif operation == "hml_project_catalog":
        target = "hml-pilot"
    if result.get("operation") != operation or result.get("target") != target:
        raise RuntimeError("response_mismatch")
    return result
