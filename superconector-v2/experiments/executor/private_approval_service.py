"""Private authorization service. No TCP listener, no approval/admin HTTP routes.

Run only under a dedicated identity with exclusive write ownership of the
approval database. The executor calls this service through a restricted Unix
socket. An independent institutional approver must provision and revoke grants.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path

import jwt
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from mission_grant_ledger import GrantRejected, LedgerUnavailable, consume_grant

APP = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
HEX40 = re.compile(r"^[a-f0-9]{40}$")


class ConsumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str
    source_sha: str


def _settings() -> dict[str, str]:
    return {
        "db": os.getenv("SUPER_APPROVAL_DB_PATH", ""),
        "issuer": os.getenv("SUPER_EXECUTOR_OIDC_ISSUER", ""),
        "audience": os.getenv("SUPER_EXECUTOR_OIDC_AUDIENCE", ""),
        "public_key": os.getenv("SUPER_EXECUTOR_OIDC_PUBLIC_KEY", "").replace("\\n", "\n"),
        "tenant": os.getenv("SUPER_EXECUTOR_TENANT_ID", ""),
        "sha": os.getenv("SUPER_EXECUTOR_SOURCE_SHA", ""),
    }


@APP.post("/internal/consume")
def consume(body: ConsumeRequest, authorization: str = Header(default="")) -> dict[str, bool]:
    settings = _settings()
    if not all(settings.values()) or not HEX40.fullmatch(settings["sha"]):
        raise HTTPException(503, "authorization_service_not_configured")
    if not authorization.startswith("Bearer ") or not authorization[7:]:
        raise HTTPException(401, "authentication_required")
    try:
        claims = jwt.decode(
            authorization[7:], settings["public_key"],
            algorithms=["RS256"], issuer=settings["issuer"],
            audience=settings["audience"],
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti"]},
            leeway=0,
        )
    except jwt.InvalidTokenError:
        raise HTTPException(401, "invalid_token") from None
    if claims.get("tenant_id") != settings["tenant"]:
        raise HTTPException(403, "tenant_not_authorized")
    if claims.get("scope") != "executor:hml:run":
        raise HTTPException(403, "insufficient_scope")
    if body.profile != claims.get("approved_profile") or body.profile not in ("probe", "syntax"):
        raise HTTPException(403, "profile_not_approved")
    if body.source_sha != settings["sha"] or claims.get("source_sha") != settings["sha"]:
        raise HTTPException(409, "source_sha_mismatch")
    if not isinstance(claims.get("iat"), int) or isinstance(claims["iat"], bool):
        raise HTTPException(403, "invalid_grant_time")
    if not isinstance(claims.get("exp"), int) or isinstance(claims["exp"], bool):
        raise HTTPException(403, "invalid_grant_time")
    if not (0 < claims["exp"] - claims["iat"] <= 300):
        raise HTTPException(403, "grant_too_long")
    try:
        consume_grant(settings["db"], claims, pinned_sha=settings["sha"])
    except GrantRejected as exc:
        raise HTTPException(403, str(exc)) from None
    except LedgerUnavailable:
        raise HTTPException(503, "approval_ledger_unavailable") from None
    return {"consumed": True}
