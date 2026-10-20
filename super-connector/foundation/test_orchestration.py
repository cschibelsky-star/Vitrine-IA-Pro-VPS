import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location("orchestration",Path(__file__).parent/"orchestration.py")
module=importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name]=module
spec.loader.exec_module(module)

def project(id="conheca-sumare-react-review"):
    return {"id":id,"workspace":{"root":"/srv/projects/"+id},
      "repository":{"url":"https://github.com/a/b.git","branch":"main","directory":"repository"},
      "docker":{"compose_file":"docker-compose.home-review.yml","project_name":"conheca-home-review"}}

def adapter(id,cap,healthy=True):
    return {"id":id,"capabilities":[cap],"healthy":healthy,"project_supported":True,"policy_allowed":True}

class RoutingTests(unittest.TestCase):
    def test_unknown_mutation_fails(self):
        p=project("city")
        p["docker"]={"compose_file":"docker-compose.yml","project_name":"city"}
        self.assertEqual(module.plan("compose_build",p,[adapter("super","docker_build")],confirm="EXECUTAR",verified={"isolated_target":True})["error"],"environment_unclassified")
    def test_no_confirmation_denied(self):
        self.assertEqual(module.plan("compose_build",project(),[adapter("super","docker_build")],verified={"isolated_target":True})["error"],"authorization_required")
    def test_capability_fallback_uses_alternative(self):
        p=module.plan("compose_build",project(),[adapter("super","docker_build",False),adapter("v5","docker_build")],confirm="EXECUTAR",verified={"isolated_target":True},registries_aligned=True)
        self.assertTrue(p["ok"])
        self.assertEqual(p["selected"],"v5")
    def test_no_unverified_production_change(self):
        self.assertEqual(module.plan("compose_build",project("city-prod"),[adapter("super","docker_build")],confirm="EXECUTAR PRODUCAO",verified={"isolated_target":True})["error"],"preflight_incomplete")
    def test_registry_drift(self):
        self.assertEqual(module.plan("compose_build",project(),[adapter("super","docker_build")],confirm="EXECUTAR",verified={"isolated_target":True},registries_aligned=False)["error"],"registry_drift_detected")
    def test_missing_build(self):
        self.assertEqual(module.plan("compose_up",project(),[adapter("super","docker_up")],confirm="EXECUTAR",verified={"isolated_target":True})["error"],"preflight_incomplete")
    def test_fallback_only_before_mutation(self):
        self.assertTrue(module.may_fallback({"ok":False,"error":"controlled_service_not_allowed"}))
        self.assertFalse(module.may_fallback({"ok":False,"error":"timeout"}))
        self.assertFalse(module.may_fallback({"ok":False,"error":"controlled_service_not_allowed"},mutation_possible=True))
    def test_manifest_alignment(self):
        p=project()
        q={"id":p["id"],"workspace_root":p["workspace"]["root"],"repository":p["repository"],"docker":p["docker"]}
        self.assertTrue(module.equivalent_manifest(p,q))
        q["docker"]={"compose_file":"different.yml","project_name":p["docker"]["project_name"]}
        self.assertFalse(module.equivalent_manifest(p,q))
    def test_unknown_operation(self):
        self.assertEqual(module.plan("shell_exec",project(),[])["error"],"unknown_operation_denied")
    def test_production_route_is_closed(self):
        result=module.plan("production_deploy",project("city-prod"),[adapter("super","production_deploy")],confirm="EXECUTAR PRODUCAO",verified={"cockpit_approved":True,"hml_tests_passed":True,"backup_verified":True,"rollback_ready":True})
        self.assertEqual(result["error"],"no_equivalent_authorized_route")

if __name__=="__main__":
    unittest.main()
