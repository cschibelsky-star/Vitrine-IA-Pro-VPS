from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import sys
import unittest

root = Path(__file__).parent
for name in ("orchestration", "dispatch_guard"):
    spec = importlib.util.spec_from_file_location("foundation."+name,root/(name+".py"))
    if name == "dispatch_guard":
        import types
        package = sys.modules.setdefault("foundation",types.ModuleType("foundation"))
        package.orchestration=sys.modules["foundation.orchestration"]
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)

guard=sys.modules["foundation.dispatch_guard"]

def manifest(root):
    return {"id":"safe-review","workspace":{"root":str(root)},
            "repository":{"url":"https://github.com/a/b.git","branch":"main","directory":"repository"},
            "docker":{"compose_file":"docker-compose.home-review.yml","project_name":"safe-review"}}

def runner(args,cwd,timeout=30):
    if args[:3]==["git","status","--porcelain"]:
        return {"ok":True,"stdout":""}
    if args[:3]==["git","rev-parse","HEAD"]:
        return {"ok":True,"stdout":"a"*40}
    if args[:3]==["docker","image","inspect"]:
        return {"ok":True,"stdout":"sha256:"+"b"*64}
    return {"ok":False,"stdout":""}

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws=Path(self.tmp.name)
        self.repo=self.ws/"repository"
        self.repo.mkdir()
        self.compose=self.repo/"docker-compose.home-review.yml"
        self.compose.write_text("services:\\n  web:\\n    image: test\\n")
        self.project=manifest(self.ws)
        self.registry=self.ws/"v5"
        self.registry.mkdir()
    def pre(self,op,confirm="EXECUTAR"):
        return guard.preflight(op,"safe-review",self.project,confirm=confirm,
             run=runner,workspace=self.ws,repository=self.repo,compose=self.compose,
             project_name="safe-review",service="web",legacy_registry=self.registry)
    def test_build_allowed_only_with_confirmation(self):
        self.assertTrue(self.pre("build")["ok"])
        self.assertEqual(self.pre("build",confirm="")["error"],"authorization_required")
    def test_up_requires_verified_image_receipt(self):
        self.assertEqual(self.pre("up")["error"],"preflight_incomplete")
        self.assertTrue(guard.remember_build(runner,self.ws,self.repo,self.compose,"safe-review","web"))
        self.assertTrue(self.pre("up")["ok"])
        self.compose.write_text("changed")
        self.assertEqual(self.pre("up")["error"],"preflight_incomplete")
    def test_drift_blocks_build(self):
        import json
        record={"id":"safe-review","workspace_root":str(self.ws),
                "repository":self.project["repository"],
                "docker":{"compose_file":"wrong.yml","project_name":"safe-review"}}
        (self.registry/"safe-review.json").write_text(json.dumps(record))
        self.assertEqual(self.pre("build")["error"],"registry_drift_detected")
    def test_unknown_environment_denied(self):
        self.project["id"]="unknown-city"
        self.project["docker"]={"compose_file":"docker-compose.yml","project_name":"unknown-city"}
        self.assertEqual(self.pre("build")["error"],"target_not_verified_hml")
    def test_production_denied_even_with_confirmation(self):
        self.project["id"]="safe-prod"
        self.assertEqual(self.pre("build",confirm="EXECUTAR PRODUCAO")["error"],"target_not_verified_hml")

if __name__ == "__main__":
    unittest.main()
