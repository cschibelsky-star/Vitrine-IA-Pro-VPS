"""Restricted OIDC authentication for Superconector V2."""

import asyncio
import os
import time

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken


class IdentityVerifier:
    def __init__(self):
        self.issuer = os.environ["SUPER_OIDC_ISSUER"]
        self.audience = os.environ["SUPER_OIDC_AUDIENCE"]
        self.resource = os.environ["SUPER_MCP_RESOURCE"]
        self.subject = os.environ["SUPER_ALLOWED_SUBJECT"]
        self.tenant = os.environ["SUPER_ALLOWED_TENANT"]
        self.jwks = PyJWKClient(
            os.environ["SUPER_OIDC_JWKS_URL"],
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )

    def validate(self, token):
        try:
            key = self.jwks.get_signing_key_from_jwt(token)

            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "require": [
                        "exp", "iat", "iss", "aud", "sub"
                    ]
                },
            )

            if claims.get("sub") != self.subject:
                return None

            if claims.get("tenant_id") != self.tenant:
                return None

            if claims.get("azp") != "super-v2-mcp":
                return None

            if claims.get("typ") != "Bearer":
                return None

            if claims["exp"] <= time.time():
                return None

            scopes = claims.get("scope", "").split()

            if "projects:read" not in scopes:
                return None

            return AccessToken(
                token=token,
                client_id="super-v2-mcp",
                scopes=scopes,
                expires_at=claims["exp"],
                resource=self.resource,
                subject=claims["sub"],
                claims={
                    "tenant_id": self.tenant,
                },
            )

        except Exception:
            return None

    async def verify_token(self, token):
        return await asyncio.to_thread(
            self.validate, token
        )
