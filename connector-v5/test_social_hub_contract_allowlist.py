"""Narrow V5 Compose policy for the inert Social Hub status sandbox."""

import ast
import unittest
from pathlib import Path

from marketing_live_patch import apply as marketing
from controlled_operations_patch import apply as controlled


class SocialHubContractAllowlistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        source = controlled(marketing(base))
        tree = ast.parse(source)
        policy_assignment = next(
            node for node in tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "CONTROLLED_COMPOSE_POLICY"
        )
        cls.policies = policy_assignment.value

    def policy_entry(self, project):
        for key, value in zip(self.policies.keys, self.policies.values):
            if isinstance(key, ast.Constant) and key.value == project:
                return value
        self.fail("Sandbox project must be in explicit allowlist")

    def test_only_one_service_and_compose_are_authorized(self):
        entry = self.policy_entry("vitrine-marketing-social-hub-contract-hml")
        values = {
            key.value: value for key, value in zip(entry.keys, entry.values)
        }
        self.assertEqual(
            set(values),
            {"compose_files", "services", "run_once", "build", "up"},
        )
        self.assertEqual(ast.literal_eval(values["compose_files"]),
                         {"docker-compose.social-hub-status-contract.yml"})
        self.assertEqual(ast.literal_eval(values["services"]), {"status_contract"})
        self.assertEqual(ast.literal_eval(values["build"]), {"status_contract"})
        self.assertEqual(ast.literal_eval(values["up"]), {"status_contract"})
        self.assertEqual(ast.unparse(values["run_once"]), "set()")

    def test_existing_projects_remain_separate(self):
        keys = [key.value for key in self.policies.keys]
        self.assertEqual(
            keys.count("vitrine-marketing-social-hub-contract-hml"), 1
        )
        self.assertIn("vitrine-ia-pro-core", keys)
        self.assertIn("vitrine-ai-social-enterprise", keys)
        self.assertNotEqual(
            ast.unparse(self.policy_entry("vitrine-marketing-social-hub-contract-hml")),
            ast.unparse(self.policy_entry("vitrine-ia-pro-core")),
        )


if __name__ == "__main__":
    unittest.main()
