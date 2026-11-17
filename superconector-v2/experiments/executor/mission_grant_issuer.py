"""Fail-closed HML mission-grant signer; no HTTP endpoint or autonomous approval.

The calling identity service MUST independently authenticate the principal and
load an approved, immutable mission record. This module never approves missions.
Do not deploy a signing key inside the executor or public MCP container.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
import re
from uuid import uuid4
import jwt

SHA40 = re.compile(r"^[a-f0-9]{40}$")
SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")
ALLOWED_PROFILES = frozenset({"probe", "syntax"})
AUDIT_SCOPE = "executor:hml:run"


class GrantDenied(ValueError):
    """A request did not meet the issuer's strict requirements."""


@dataclass(frozen=True)
class ApprovedMission:
    mission_id: str
    approval_id: str
    tenant_id: str
    approved_profile: str
    source_sha: str
    approved_subject: str


def issue_mission_grant(
    *,
    authenticated_subject: str,
    mission: ApprovedMission,
    lookup_approval: Callable[[str, str], ApprovedMission | None],
    private_key_pem: str,
    issuer: str,
    audience: str,
    expected_tenant: str,
    pinned_source_sha: str,
    now: datetime | None = None,
    ttl_seconds: int = 120,
) -> str:
    """Sign only after the trusted caller supplies a matching stored approval.

    lookup_approval is provided by an authenticated institutional service; never
    resolve an approval from untrusted request body alone. The authorization
    service must separately enforce revocation and single-use/replay controls.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise GrantDenied("timezone_required")
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or not 1 <= ttl_seconds <= 300:
        raise GrantDenied("invalid_ttl")
    if not all(isinstance(x, str) and SAFE_ID.fullmatch(x) for x in (
        authenticated_subject, mission.mission_id, mission.approval_id,
        mission.tenant_id, mission.approved_subject, expected_tenant
    )):
        raise GrantDenied("invalid_identity")
    if not issuer.startswith("https://") or not audience or not private_key_pem:
        raise GrantDenied("issuer_not_configured")
    if not SHA40.fullmatch(pinned_source_sha) or mission.source_sha != pinned_source_sha:
        raise GrantDenied("source_sha_mismatch")
    if mission.tenant_id != expected_tenant or mission.approved_subject != authenticated_subject:
        raise GrantDenied("identity_or_tenant_mismatch")
    if mission.approved_profile not in ALLOWED_PROFILES:
        raise GrantDenied("profile_not_allowed")
    record = lookup_approval(mission.mission_id, mission.approval_id)
    if record is None or record != mission:
        raise GrantDenied("approval_not_confirmed")
    issued_at = int(now.timestamp())
    claims = {
        "iss": issuer, "aud": audience, "sub": authenticated_subject,
        "jti": str(uuid4()),
        "iat": issued_at, "nbf": issued_at, "exp": issued_at + ttl_seconds,
        "tenant_id": mission.tenant_id, "mission_id": mission.mission_id,
        "approval_id": mission.approval_id, "approved_profile": mission.approved_profile,
        "source_sha": pinned_source_sha, "scope": AUDIT_SCOPE,
    }
    return jwt.encode(claims, private_key_pem, algorithm="RS256")
