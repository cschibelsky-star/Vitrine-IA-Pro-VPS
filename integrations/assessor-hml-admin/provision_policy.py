"""Policy gate for Assessor Online HML admin provisioning.

Source-only adapter. The production MCP server must supply an authenticated
principal and a separately reviewed, fixed-operation executor. No shell access.
"""
from dataclasses import dataclass
from typing import Callable, Mapping

PROJECT = "assessor-online-pr137-current-hml"
SERVICE = "assessor_laravel"
HOST = "p000009.hml.vitrineiapro.com.br"
COMMAND = "assessor:provision-hml-admin"
TENANT = "gabinete-demonstracao"


class ProvisionDenied(Exception):
    """Provisioning rejected before invoking the backend."""


@dataclass(frozen=True)
class ProvisionRequest:
    project_id: str
    service: str
    hostname: str
    email: str
    confirmation: str
    ticket: str


def provision_hml_admin(
    request: ProvisionRequest,
    *,
    principal: Mapping[str, object],
    runtime: Mapping[str, object],
    execute_fixed: Callable[[str, str, str, str], Mapping[str, object]],
    audit: Callable[[Mapping[str, object]], None],
) -> Mapping[str, object]:
    """Fail closed; invoke only the injected fixed-operation executor.

    The executor must independently enforce authorization and verify the
    running container/APP_ENV/APP_URL, flag and email allowlist server-side.
    No password or secret is accepted or returned by this interface.
    """
    if request.confirmation != "EXECUTAR":
        raise ProvisionDenied("confirmation_required")
    if not isinstance(request.ticket, str) or not request.ticket.strip():
        raise ProvisionDenied("audit_ticket_required")
    if (request.project_id, request.service, request.hostname) != (PROJECT, SERVICE, HOST):
        raise ProvisionDenied("target_not_allowed")
    if principal.get("authenticated") is not True or principal.get("scope") != "assessor.hml.admin.provision":
        raise ProvisionDenied("permission_denied")
    if runtime.get("environment") != "homologation" or runtime.get("hostname") != HOST:
        raise ProvisionDenied("runtime_not_hml")
    if runtime.get("provision_enabled") is not True:
        raise ProvisionDenied("provision_disabled")
    allowed_email = runtime.get("allowed_admin_email")
    if not isinstance(allowed_email, str) or request.email.strip().casefold() != allowed_email.casefold():
        raise ProvisionDenied("email_not_allowlisted")
    if not isinstance(runtime.get("sso_configured"), bool) or runtime["sso_configured"] is not True:
        raise ProvisionDenied("sso_not_configured")
    audit({"event": "assessor_hml_admin_provision_requested", "ticket": request.ticket,
           "project": PROJECT, "principal_id": principal.get("id"), "outcome": "started"})
    try:
        result = execute_fixed(PROJECT, SERVICE, COMMAND, request.email.strip())
    except Exception:
        audit({"event": "assessor_hml_admin_provision_result", "ticket": request.ticket,
               "project": PROJECT, "outcome": "backend_error"})
        raise
    ok = result.get("ok") is True
    audit({"event": "assessor_hml_admin_provision_result", "ticket": request.ticket,
           "project": PROJECT, "outcome": "reported_success" if ok else "failed"})
    return {"ok": ok, "status": "provision_reported" if ok else "provision_failed",
            "requires_independent_access_validation": True}
