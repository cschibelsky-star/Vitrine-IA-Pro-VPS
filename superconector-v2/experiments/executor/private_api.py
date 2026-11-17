"""Private HML-only executor HTTP gateway. Not part of public MCP.

Runs fixed experimental profiles inside an independently sandboxed Linux container.
Deployment must supply a pinned source SHA and configured OIDC public key.
"""
from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Any
import jwt
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from runner import run_profile

HEX40 = re.compile(r"^[a-f0-9]{40}$")
APP = FastAPI(title="Superconector V2 private HML executor", docs_url=None,
              redoc_url=None, openapi_url=None)

class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str
    source_sha: str
    approval: str

def _settings() -> dict[str, Any]:
    return {
        "enabled": os.getenv("SUPER_EXECUTOR_HML_ENABLED", "") == "true",
        "issuer": os.getenv("SUPER_EXECUTOR_OIDC_ISSUER", ""),
        "audience": os.getenv("SUPER_EXECUTOR_OIDC_AUDIENCE", ""),
        "public_key": os.getenv("SUPER_EXECUTOR_OIDC_PUBLIC_KEY", "").replace("\\n", "\n"),
        "sha": os.getenv("SUPER_EXECUTOR_SOURCE_SHA", ""),
        "tenant": os.getenv("SUPER_EXECUTOR_TENANT_ID", ""),
        "server_root": os.getenv("SUPER_EXECUTOR_SERVER_ROOT", "/workspace"),
    }

def _identity(request: Request, settings: dict[str, Any]) -> dict[str, Any]:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not auth[7:]:
        raise HTTPException(401, "authentication_required")
    if not all(settings[k] for k in ("issuer", "audience", "public_key", "tenant")):
        raise HTTPException(503, "identity_not_configured")
    try:
        claims = jwt.decode(auth[7:], settings["public_key"], algorithms=["RS256"],
                            issuer=settings["issuer"], audience=settings["audience"],
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
                            leeway=0)
    except jwt.InvalidTokenError:
        raise HTTPException(401, "invalid_token") from None
    # A short-lived, signed mission grant binds the approved profile to a mission.
    try:
        issued_at, expires_at = int(claims["iat"]), int(claims["exp"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(403, "mission_grant_invalid") from None
    if expires_at <= issued_at or expires_at - issued_at > 300:
        raise HTTPException(403, "mission_grant_too_long")
    if not all(isinstance(claims.get(k), str) and claims[k] for k in ("mission_id", "approval_id", "approved_profile")):
        raise HTTPException(403, "mission_approval_missing")
    if claims.get("tenant_id") != settings["tenant"]:
        raise HTTPException(403, "tenant_not_authorized")
    scopes = claims.get("scope", "")
    if not isinstance(scopes, str) or "executor:hml:run" not in scopes.split():
        raise HTTPException(403, "insufficient_scope")
    return claims

@APP.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "alive", "executor_enabled": _settings()["enabled"],
            "environment": "isolated-hml-only"}

@APP.post("/v1/hml/execute")
def execute(body: ExecuteRequest, request: Request) -> dict[str, Any]:
    s = _settings()
    if not s["enabled"]:
        raise HTTPException(503, "executor_disabled")
    claims = _identity(request, s)
    if body.approval != "EXECUTAR":
        raise HTTPException(403, "explicit_approval_required")
    if not HEX40.fullmatch(s["sha"]) or body.source_sha != s["sha"]:
        raise HTTPException(409, "source_sha_mismatch")
    if claims["approved_profile"] != body.profile:
        raise HTTPException(403, "profile_not_approved_for_mission")
    if body.profile not in ("probe", "syntax"):
        raise HTTPException(403, "profile_not_allowed")
    # Never accept shell, paths, environment or commands from clients.
    result = run_profile(body.profile, Path(s["server_root"]), approval="EXECUTAR",
                         context="isolated-ci-only", source_sha=s["sha"])
    return {"identity": {"subject": claims["sub"], "tenant_id": s["tenant"],
                         "mission_id": claims["mission_id"], "approval_id": claims["approval_id"]},
            "execution": result, "environment": "isolated-hml-only",
            "production_allowed": False}
