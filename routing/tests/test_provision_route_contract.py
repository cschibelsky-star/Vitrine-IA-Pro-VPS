"""Tests for the canonical HML route allocator, without touching the live registry."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "provision_route.py"
spec = importlib.util.spec_from_file_location("route_allocator", MODULE_PATH)
allocator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(allocator)


class RouteProvisionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        registry = {
            "schema_version": "2.0",
            "base_domains": {"homologation": "hml.vitrineiapro.com.br", "customer_root": "vitrineiapro.com.br"},
            "code_policy": {"project_prefix": "p", "customer_prefix": "c", "width": 6, "project_next": 5, "customer_next": 1},
            "reserved_root_labels": ["core", "hml"],
            "network": "n8n-traefik_app_network",
            "routes": [{"id": "p000004-hml", "deployment_code": "p000004", "hostname": "p000004.hml.vitrineiapro.com.br"}],
        }
        self.registry = self.root / "routes.json"
        self.registry.write_text(json.dumps(registry), encoding="utf-8")
        p1 = patch.object(allocator, "REGISTRY", self.registry)
        p2 = patch.object(allocator, "LOCK", self.root / ".routes.lock")
        p1.start(); p2.start()
        self.addCleanup(p2.stop); self.addCleanup(p1.stop)

    def routes(self):
        return json.loads(self.registry.read_text(encoding="utf-8"))

    def test_project_route_matches_activator_contract(self):
        allocator.allocate("project", "assessor-online-trial-hml", "http://assessor-online-trial-hml-assessor_web-1:8080", "/up", "assessor")
        doc = self.routes()
        route = doc["routes"][-1]
        self.assertEqual(route["id"], "p000005-hml")
        self.assertEqual(route["hostname"], "p000005.hml.vitrineiapro.com.br")
        self.assertEqual(route["friendly_aliases"], ["assessor.hml.vitrineiapro.com.br"])
        self.assertEqual(route["network"], "n8n-traefik_app_network")
        self.assertEqual(route["entrypoint"], "websecure")
        self.assertEqual(route["cert_resolver"], "le")
        self.assertEqual(route["status"], "planned")
        self.assertEqual(route["health_path"], "/up")
        self.assertEqual(doc["code_policy"]["project_next"], 6)

    def test_rejects_loopback_without_modifying_registry(self):
        before = self.registry.read_bytes()
        with self.assertRaisesRegex(ValueError, "internal container"):
            allocator.allocate("project", "assessor-online-trial-hml", "http://127.0.0.1:18782", "/up", "assessor")
        self.assertEqual(before, self.registry.read_bytes())

    def test_rejects_unknown_network(self):
        doc = self.routes()
        doc["network"] = "public_internet"
        self.registry.write_text(json.dumps(doc))
        with self.assertRaisesRegex(ValueError, "unsupported routing network"):
            allocator.allocate("project", "assessor", "http://assessor_web:8080", "/up", None)

    def test_rejects_invalid_health_path(self):
        with self.assertRaisesRegex(ValueError, "invalid health path"):
            allocator.allocate("project", "assessor", "http://assessor_web:8080", "https://evil.test", None)

    def test_rejects_duplicate_friendly_hostname(self):
        allocator.allocate("project", "assessor", "http://assessor_web:8080", "/up", "assessor")
        with self.assertRaisesRegex(ValueError, "already reserved"):
            allocator.allocate("project", "another", "http://another_web:8080", "/up", "assessor")


if __name__ == "__main__":
    unittest.main()
