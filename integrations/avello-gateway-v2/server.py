"""Isolated read-only MCP gateway V2. No inference, no remote execution."""
import json
import os
import urllib.error
import urllib.request
from mcp.server.fastmcp import FastMCP
from auth_guard import ProtectedMCP

BASE_URL = "https://avellogateway.online"
MAX_BYTES = 1024 * 1024
mcp = FastMCP("Vitrine Avello Gateway V2", stateless_http=True, json_response=True)

@mcp.tool()
def gateway_status() -> dict:
    """Read configuration readiness without exposing any credential."""
    return {"service": "vitrine-avello-gateway-v2", "mode": "read_only",
            "gateway_key_present": bool(os.getenv("AVELLO_V2_API_KEY")),
            "inference_enabled": False, "remote_execution": False}

@mcp.tool()
def gateway_models() -> dict:
    """GET fixed model catalog, never inference; no redirects or secret disclosure."""
    key = os.getenv("AVELLO_V2_API_KEY", "")
    if not key:
        return {"status": "not_configured"}
    request = urllib.request.Request(
        BASE_URL + "/v1/models",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        method="GET")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=12) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return {"status": "invalid_response", "reason": "too_large"}
        payload = json.loads(raw)
        records = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            return {"status": "invalid_response"}
        models = sorted({r["id"] for r in records if isinstance(r, dict)
                         and isinstance(r.get("id"), str)
                         and 0 < len(r["id"]) <= 100
                         and all(c.isascii() and (c.isalnum() or c in "-._:/") for c in r["id"])})
        return {"status": "ok", "models": models[:200]}
    except urllib.error.HTTPError as exc:
        return {"status": "provider_error", "http_status": exc.code}
    except (urllib.error.URLError, TimeoutError):
        return {"status": "network_error"}
    except (ValueError, TypeError):
        return {"status": "invalid_response"}

# DISABLED by default. Signed approval must originate from a trusted issuer.
# This is source-only integration: no deployment or credential provisioned.
if os.getenv("VIA_GITHUB_DISPATCH_TOOL_ENABLED", "") == "true":
    from dispatch_request_context import current_approval
    from dispatch_authorization import authorize, AuthorizationDenied
    from dispatch_audit import record, AuditUnavailable
    from github_actions_dispatch import dispatch, DispatchError, REPOSITORY, WORKFLOW, BRANCH

    @mcp.tool()
    def via_android_request_validation() -> dict:
        """Request the fixed source-only VIA Android validation workflow."""
        approval = current_approval.get()
        if approval is None:
            return {"status": "blocked", "reason": "signed_approval_required"}
        try:
            authorize(approval.identity, approval.nonce, approval.issued_at, approval.signature)
        except AuthorizationDenied as exc:
            return {"status": "blocked", "reason": str(exc)}
        # The approval is consumed before any network call.
        # If audit storage is unavailable, fail closed before dispatch.
        try:
            record(approval.identity, approval.nonce, "blocked", "dispatch_attempt")
        except AuditUnavailable:
            return {"status": "blocked", "reason": "audit_unavailable"}
        try:
            result = dispatch(REPOSITORY, WORKFLOW, BRANCH)
            record(approval.identity, approval.nonce, "accepted_not_verified")
            return result
        except DispatchError as exc:
            try:
                record(approval.identity, approval.nonce, "dispatch_error", str(exc))
            except AuditUnavailable:
                return {"status": "blocked", "reason": "audit_unavailable"}
            return {"status": "blocked", "reason": str(exc)}
        except AuditUnavailable:
            return {"status": "blocked", "reason": "audit_unavailable"}

app = ProtectedMCP(mcp.streamable_http_app())
