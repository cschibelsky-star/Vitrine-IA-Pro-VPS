import importlib.util
import pathlib
import unittest

path = pathlib.Path(__file__).with_name("provision_policy.py")
spec = importlib.util.spec_from_file_location("provision_policy", path)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class ProvisionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.audit = []
        self.req = mod.ProvisionRequest(mod.PROJECT, mod.SERVICE, mod.HOST,
                                        "admin@example.test", "EXECUTAR", "ISSUE-62")
        self.principal = {"authenticated": True, "scope": "assessor.hml.admin.provision", "id": "operator"}
        self.runtime = {"environment": "homologation", "hostname": mod.HOST,
                        "provision_enabled": True, "allowed_admin_email": "admin@example.test",
                        "sso_configured": True}

    def invoke(self, req=None, principal=None, runtime=None):
        def executor(*args):
            self.calls.append(args)
            return {"ok": True}
        return mod.provision_hml_admin(
            req or self.req, principal=self.principal if principal is None else principal,
            runtime=self.runtime if runtime is None else runtime,
            execute_fixed=executor, audit=self.audit.append)

    def test_authorized_calls_only_fixed_operation(self):
        result = self.invoke()
        self.assertTrue(result["ok"])
        self.assertTrue(result["requires_independent_access_validation"])
        self.assertEqual(self.calls, [(mod.PROJECT, mod.SERVICE, mod.COMMAND, "admin@example.test")])
        self.assertEqual(len(self.audit), 2)

    def test_rejects_wrong_target(self):
        for kwargs in ({"project_id": "production"}, {"service": "other"},
                       {"hostname": "example.com"}, {"confirmation": "Continue"}, {"ticket": ""}):
            req = mod.ProvisionRequest(**{**vars(self.req), **kwargs})
            with self.subTest(kwargs=kwargs), self.assertRaises(mod.ProvisionDenied):
                self.invoke(req=req)
        self.assertEqual(self.calls, [])

    def test_rejects_unauthorized_principal(self):
        for principal in ({}, {"authenticated": True, "scope": "read"},
                          {"authenticated": False, "scope": "assessor.hml.admin.provision"}):
            with self.subTest(principal=principal), self.assertRaises(mod.ProvisionDenied):
                self.invoke(principal=principal)
        self.assertEqual(self.calls, [])

    def test_rejects_unverified_runtime(self):
        for patch in ({"environment": "production"}, {"hostname": "other"},
                      {"provision_enabled": False}, {"allowed_admin_email": "other@example.test"},
                      {"sso_configured": False}):
            with self.subTest(patch=patch), self.assertRaises(mod.ProvisionDenied):
                self.invoke(runtime={**self.runtime, **patch})
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
