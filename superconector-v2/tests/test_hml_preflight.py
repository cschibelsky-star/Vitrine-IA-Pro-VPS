"""Static HML gates; NOT an MCP connectivity test."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"

class HMLPreflight(unittest.TestCase):
    def test_draft_has_no_old_app_binding(self):
        manifest = json.loads((ROOT / "plugin-draft/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "vitrine-superconector-v2")
        self.assertNotIn("apps", manifest)
        self.assertNotIn("apps", manifest.get("extensions", {}).get("com.openai", {}))

    def test_public_mcp_is_informational_only(self):
        tree = ast.parse((SERVER / "main.py").read_text(encoding="utf-8"))
        tools = [
            n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and d.func.attr == "tool" for d in n.decorator_list
            )
        ]
        self.assertEqual(tools, ["public_capabilities", "connection_requirements", "service_readiness"])

    def test_gateway_fail_closed(self):
        code = (SERVER / "gateway.py").read_text(encoding="utf-8")
        self.assertIn('"false").lower() == "true"', code)
        self.assertIn("follow_redirects=False", code)
        self.assertIn("trust_env=False", code)
        self.assertIn('algorithms=["RS256"]', code)

    def test_no_privileged_compose_mounts(self):
        for name in ("docker-compose.hml.yml", "docker-compose.gateway.hml.yml"):
            content = (SERVER / name).read_text(encoding="utf-8")
            for forbidden in ("docker.sock", "/root/.ssh", "/srv/projects", "/srv/tvsumare", "privileged: true"):
                with self.subTest(name=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, content)
            self.assertIn("read_only: true", content)
            self.assertIn("no-new-privileges:true", content)

    def test_mcp_bind_is_container_reachable(self):
        content = (SERVER / "main.py").read_text(encoding="utf-8")
        self.assertIn('host="0.0.0.0"', content)
        self.assertIn("port=8000", content)
        self.assertIn('mcp.run(transport="streamable-http")', content)

    def test_remote_publication_not_misrepresented(self):
        self.assertFalse((ROOT / "plugin-draft/mcp.json").exists(),
                         "Do not invent an MCP HTTPS URL before real deployment")

if __name__ == "__main__":
    unittest.main()
