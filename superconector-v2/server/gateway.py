"""Tenant-scoped, read-only bridge prototype. Not exposed as a public MCP tool.

Trusted OIDC identity, tenant allowlist and fail-closed upstream controls.
The proposed V5 HTTP route is NOT VERIFIED; integration is disabled by default.
"""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass
from typing import Any
import httpx
import jwt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

@dataclass(frozen=True)
class Settings:
    oidc_issuer: str
    oidc_audience: str
    oidc_public_key: str
    tenant_projects: dict[str, frozenset[str]]
    v5_base_url: str
    v5_service_token: str
    v5_enabled: bool

    @classmethod
    def from_environment(cls) -> "Settings":
        raw = json.loads(os.environ.get("SUPER_TENANT_PROJECTS_JSON", "{}"))
        if not isinstance(raw, dict) or any(
            not isinstance(k, str) or not isinstance(v, list)
            or any(not isinstance(p, str) for p in v)
            for k, v in raw.items()
        ):
            raise ValueError("invalid tenant-project mapping")
        return cls(
            oidc_issuer=os.environ.get("SUPER_OIDC_ISSUER", ""),
            oidc_audience=os.environ.get("SUPER_OIDC_AUDIENCE", ""),
            oidc_public_key=os.environ.get("SUPER_OIDC_PUBLIC_KEY", "").replace("\\n", "\n"),
            tenant_projects={tenant: frozenset(projects) for tenant, projects in raw.items()},
            v5_base_url=os.environ.get("SUPER_V5_BASE_URL", ""),
            v5_service_token=os.environ.get("SUPER_V5_SERVICE_TOKEN", ""),
            v5_enabled=os.environ.get("SUPER_V5_READ_ENABLED", "false").lower() == "true",
        )

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_ALLOWED_RESPONSE_KEYS = frozenset({
    "project_id", "name", "status", "health", "repository_exists", "workspace_exists",
})

def _claims(request: Request, settings: Settings) -> dict[str, Any]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not auth[7:]:
        raise HTTPException(status_code=401, detail="authentication_required")
    if not all((settings.oidc_issuer, settings.oidc_audience, settings.oidc_public_key)):
        raise HTTPException(status_code=503, detail="identity_provider_not_configured")
    try:
        token = jwt.decode(
            auth[7:], settings.oidc_public_key, algorithms=["RS256"],
            issuer=settings.oidc_issuer, audience=settings.oidc_audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=0,
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid_access_token") from None
    if not isinstance(token.get("tenant_id"), str) or not token["tenant_id"]:
        raise HTTPException(status_code=403, detail="tenant_binding_required")
    if not isinstance(token.get("scope"), str) or "projects:read" not in token["scope"].split():
        raise HTTPException(status_code=403, detail="insufficient_scope")
    return token

def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    app = FastAPI(title="Vitrine Superconector V2 Tenant Gateway", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {
            "status": "alive",
            "operational_access": "disabled" if not settings.v5_enabled else "restricted",
        }

    @app.get("/v1/projects/{project_id}/status")
    async def project_status(project_id: str, request: Request) -> JSONResponse:
        claims = _claims(request, settings)
        tenant_id = claims["tenant_id"]
        if not _SLUG.fullmatch(project_id) or project_id not in settings.tenant_projects.get(tenant_id, frozenset()):
            raise HTTPException(status_code=403, detail="resource_not_authorized")
        if not settings.v5_enabled:
            raise HTTPException(status_code=503, detail="upstream_integration_disabled")
        if not (settings.v5_service_token and settings.v5_base_url.startswith("https://")):
            raise HTTPException(status_code=503, detail="upstream_not_configured")
        base = settings.v5_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(
                timeout=5.0, follow_redirects=False, transport=transport, trust_env=False,
            ) as client:
                response = await client.get(
                    f"{base}/v1/projects/{project_id}/status",
                    headers={
                        "Authorization": f"Bearer {settings.v5_service_token}",
                        "Accept": "application/json",
                    },
                )
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="upstream_unavailable") from None
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail="upstream_error")
        try:
            obj = response.json()
        except ValueError:
            raise HTTPException(status_code=502, detail="upstream_invalid_response") from None
        if not isinstance(obj, dict) or obj.get("project_id") != project_id:
            raise HTTPException(status_code=502, detail="upstream_identity_mismatch")
        return JSONResponse({key: obj[key] for key in _ALLOWED_RESPONSE_KEYS if key in obj})

    return app

app = create_app()
