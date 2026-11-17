"""Integration tests exercise the real HTTP boundary and fixed Linux subprocess."""
import os
import pathlib
import time
import unittest
import sqlite3
import tempfile
import subprocess
import sys
from uuid import uuid4
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from private_api import APP
from mission_grant_ledger import SCHEMA

ROOT = pathlib.Path(__file__).resolve().parents[2] / "server"
SHA = "a" * 40

class PrivateApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        from cryptography.hazmat.primitives import serialization
        cls.private_key = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode()
        cls.public_key = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = str(pathlib.Path(self.temp.name) / "approvals.sqlite")
        with sqlite3.connect(self.ledger) as con:
            con.executescript(SCHEMA)
            con.execute(
                "INSERT INTO approved_missions VALUES (?,?,?,?,?,?,?,?)",
                ("mission-test-1", "approval-test-1", "tenant-hml",
                 "tester", "probe", SHA, int(time.time()) + 600, None)
            )
        self.socket = str(pathlib.Path(self.temp.name) / "approval.sock")
        self.env = patch.dict(os.environ, {
            "SUPER_EXECUTOR_HML_ENABLED": "true",
            "SUPER_EXECUTOR_OIDC_ISSUER": "https://example.invalid/oidc",
            "SUPER_EXECUTOR_OIDC_AUDIENCE": "super-executor-hml",
            "SUPER_EXECUTOR_OIDC_PUBLIC_KEY": self.public_key,
            "SUPER_EXECUTOR_TENANT_ID": "tenant-hml",
            "SUPER_EXECUTOR_SOURCE_SHA": SHA,
            "SUPER_EXECUTOR_SERVER_ROOT": str(ROOT),
            "SUPER_EXECUTOR_APPROVAL_SOCKET": self.socket,
            "SUPER_APPROVAL_DB_PATH": self.ledger,
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.auth_server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "private_approval_service:APP",
             "--uds", self.socket, "--no-access-log"],
            env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(pathlib.Path(__file__).resolve().parent),
        )
        self.addCleanup(self.stop_server)
        for _ in range(100):
            if pathlib.Path(self.socket).is_socket():
                break
            if self.auth_server.poll() is not None:
                self.fail("private authorization service exited unexpectedly")
            time.sleep(0.05)
        else:
            self.fail("private authorization socket did not initialize")
        self.client = TestClient(APP)

    def stop_server(self):
        self.auth_server.terminate()
        try:
            self.auth_server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.auth_server.kill()
            self.auth_server.wait(timeout=3)


    def token(self, **changes):
        now = int(time.time())
        claims = dict(iss="https://example.invalid/oidc", aud="super-executor-hml",
                      sub="tester", iat=now, nbf=now, exp=now+90, jti=str(uuid4()),
                      source_sha=SHA,
                      tenant_id="tenant-hml", scope="executor:hml:run",
                      mission_id="mission-test-1", approval_id="approval-test-1",
                      approved_profile="probe")
        claims.update(changes)
        return jwt.encode(claims, self.private_key, algorithm="RS256")

    def invoke(self, token=None, **changes):
        data = {"profile": "probe", "source_sha": SHA, "approval": "EXECUTAR"}
        data.update(changes)
        return self.client.post("/v1/hml/execute", json=data,
                                headers={"Authorization": "Bearer " + (token or self.token())})

    def test_real_probe_over_authenticated_api(self):
        response = self.invoke()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["execution"]
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("vitrine_executor_probe_ok", result["stdout"])
        self.assertFalse(result["production_allowed"])

    def test_replay_same_token_rejected(self):
        token = self.token()
        self.assertEqual(self.invoke(token=token).status_code, 200)
        second = self.invoke(token=token)
        self.assertEqual(second.status_code, 403)
        self.assertEqual(second.json()["detail"], "approval_rejected")

    def test_second_token_same_approval_rejected(self):
        self.assertEqual(self.invoke().status_code, 200)
        self.assertEqual(self.invoke().status_code, 403)

    def test_revoked_approval_rejected(self):
        with sqlite3.connect(self.ledger) as con:
            con.execute("UPDATE approved_missions SET revoked_at=? WHERE mission_id=?",
                        (int(time.time()), "mission-test-1"))
        self.assertEqual(self.invoke().status_code, 403)

    def test_ledger_unavailable_is_fail_closed(self):
        os.environ["SUPER_EXECUTOR_APPROVAL_SOCKET"] = ""
        response = self.invoke()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "approval_service_unavailable")

    def test_missing_bearer(self):
        self.assertEqual(self.client.post("/v1/hml/execute", json={
            "profile": "probe", "source_sha": SHA, "approval": "EXECUTAR"
        }).status_code, 401)

    def test_invalid_signature(self):
        token = self.token() + "bad"
        self.assertEqual(self.invoke(token=token).status_code, 401)

    def test_wrong_tenant(self):
        self.assertEqual(self.invoke(token=self.token(tenant_id="another")).status_code, 403)

    def test_wrong_scope(self):
        self.assertEqual(self.invoke(token=self.token(scope="projects:read")).status_code, 403)

    def test_mission_profile_binding(self):
        self.assertEqual(self.invoke(token=self.token(approved_profile="syntax")).status_code, 403)

    def test_missing_signed_approval(self):
        self.assertEqual(self.invoke(token=self.token(approval_id="")).status_code, 403)

    def test_long_lived_grant(self):
        now = int(time.time())
        self.assertEqual(self.invoke(token=self.token(iat=now, exp=now + 900)).status_code, 403)

    def test_sha_mismatch(self):
        self.assertEqual(self.invoke(source_sha="b"*40).status_code, 409)

    def test_unknown_profile(self):
        self.assertEqual(self.invoke(profile="shell").status_code, 403)

    def test_missing_approval(self):
        self.assertEqual(self.invoke(approval="").status_code, 403)

    def test_extra_fields_rejected(self):
        self.assertEqual(self.invoke(command="whoami").status_code, 422)

    def test_disabled_by_default(self):
        os.environ["SUPER_EXECUTOR_HML_ENABLED"] = "false"
        self.assertEqual(self.invoke().status_code, 503)

if __name__ == "__main__":
    unittest.main()
