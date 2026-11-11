from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "main.py"
COMPOSE = (ROOT / "server" / "docker-compose.hml.yml").read_text()

class PublicMcpSafetyTests(unittest.TestCase):
    def test_server_has_only_public_tools(self):
        tree = ast.parse(SERVER.read_text())
        tools = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool"
                for d in node.decorator_list
            ):
                tools.append(node.name)
        self.assertEqual(tools, ["public_capabilities", "connection_requirements", "service_readiness"])

    def test_no_dangerous_runtime_mounts(self):
        for forbidden in ("docker.sock", "/srv/", "/root/.ssh", "privileged: true", "network_mode: host"):
            self.assertNotIn(forbidden, COMPOSE)
        self.assertIn("read_only: true", COMPOSE)
        self.assertIn("cap_drop: [ALL]", COMPOSE)
        self.assertIn("127.0.0.1:8878:8000", COMPOSE)

    def test_no_dynamic_execution(self):
        content = SERVER.read_text()
        for forbidden in ("subprocess", "os.system", "eval(", "exec(", "docker inspect", "requests.get"):
            self.assertNotIn(forbidden, content)

if __name__ == "__main__":
    unittest.main()
