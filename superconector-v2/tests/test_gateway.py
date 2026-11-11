import asyncio
import sys
import time
import unittest
from pathlib import Path
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from gateway import Settings, create_app

class TenantGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private_key = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
        )
        cls.public_key = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    def settings(self, enabled=True):
        return Settings(
            "https://idp.example.test/", "super-v2", self.public_key,
            {"tenant-a": frozenset({"tvsumare"}), "tenant-b": frozenset({"factory"})},
            "https://v5.example.test", "synthetic-bridge-token", enabled,
        )

    def token(self, tenant="tenant-a", scope="projects:read", **extra):
        now = int(time.time())
        claims = dict(sub="test-user", iss="https://idp.example.test/", aud="super-v2",
                      iat=now, exp=now + 300, tenant_id=tenant, scope=scope)
        claims.update(extra)
        return jwt.encode(claims, self.private_key, algorithm="RS256")

    def request(self, settings, token=None, path="/v1/projects/tvsumare/status", responder=None):
        calls = []
        def handler(req):
            calls.append(req)
            if responder:
                return responder(req)
            return httpx.Response(200, json={
                "project_id": "tvsumare", "health": "healthy", "secret": "NEVER",
            })
        app = create_app(settings, httpx.MockTransport(handler))
        async def run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://local",
            ) as client:
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                return await client.get(path, headers=headers)
        return asyncio.run(run()), calls

    def test_missing_token(self):
        response, calls = self.request(self.settings())
        self.assertEqual((response.status_code, len(calls)), (401, 0))

    def test_cross_tenant_denied_without_upstream_call(self):
        response, calls = self.request(self.settings(), self.token(tenant="tenant-b"))
        self.assertEqual((response.status_code, len(calls)), (403, 0))

    def test_wrong_scope(self):
        response, calls = self.request(self.settings(), self.token(scope="projects:write"))
        self.assertEqual((response.status_code, len(calls)), (403, 0))

    def test_wrong_audience(self):
        response, calls = self.request(self.settings(), self.token(aud="other"))
        self.assertEqual((response.status_code, len(calls)), (401, 0))

    def test_expired(self):
        response, calls = self.request(self.settings(), self.token(exp=int(time.time()) - 1))
        self.assertEqual((response.status_code, len(calls)), (401, 0))

    def test_missing_tenant_binding(self):
        response, calls = self.request(self.settings(), self.token(tenant_id=""))
        self.assertEqual((response.status_code, len(calls)), (403, 0))

    def test_disabled_by_default(self):
        response, calls = self.request(self.settings(False), self.token())
        self.assertEqual((response.status_code, len(calls)), (503, 0))

    def test_allowed_read_only_and_response_filtered(self):
        response, calls = self.request(self.settings(), self.token())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"project_id": "tvsumare", "health": "healthy"})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].url.host, "v5.example.test")
        self.assertEqual(calls[0].method, "GET")

    def test_upstream_redirect_rejected(self):
        response, calls = self.request(
            self.settings(), self.token(),
            responder=lambda req: httpx.Response(302, headers={"Location": "https://evil.test"}),
        )
        self.assertEqual((response.status_code, len(calls)), (502, 1))

    def test_upstream_mismatched_project_rejected(self):
        response, calls = self.request(
            self.settings(), self.token(),
            responder=lambda req: httpx.Response(200, json={"project_id": "factory"}),
        )
        self.assertEqual((response.status_code, len(calls)), (502, 1))

    def test_unknown_project_id(self):
        response, calls = self.request(self.settings(), self.token(), path="/v1/projects/other/status")
        self.assertEqual((response.status_code, len(calls)), (403, 0))

    def test_no_mutations(self):
        app = create_app(self.settings())
        routes = [(route.path, route.methods) for route in app.routes if hasattr(route, "methods")]
        self.assertFalse(any(
            "POST" in methods or "DELETE" in methods or "PUT" in methods or "PATCH" in methods
            for _, methods in routes
        ))

if __name__ == "__main__":
    unittest.main()
