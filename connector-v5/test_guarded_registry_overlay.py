"""Validate the real guarded startup composition without deployment."""
import ast
import json
import sys
import types
import unittest
from pathlib import Path

from fastmcp import Client
from marketing_live_patch import apply as marketing
from controlled_operations_patch import apply as controlled
from registry_runtime_overlay import apply as overlay

GUARD_ROOT = Path(__file__).resolve().parents[1] / "guard-stage-20261010"
sys.path.insert(0, str(GUARD_ROOT))
from install_runtime_publication_guard import independent_overlay


def legacy_source():
    source = controlled(marketing(Path(__file__).with_name("main.py").read_text()))
    lines = source.splitlines(keepends=True)
    for node in sorted(
        [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
         and n.name in {"_controlled_runtime_env_path", "project_manifest_branch_configure"}],
        key=lambda n: n.lineno, reverse=True,
    ):
        start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
        del lines[start:node.end_lineno]
    return "".join(lines).replace(
        "    runtime_target = _controlled_runtime_env_path(manifest)",
        "    runtime_target, _ = _runtime_config(manifest)",
    )


class OverlayTests(unittest.TestCase):
    def test_legacy_baseline_is_updated_and_compiles(self):
        candidate = overlay(legacy_source())
        compile(candidate, "<legacy-overlay>", "exec")
        self.assertIn("def project_manifest_branch_configure(", candidate)
        self.assertIn("runtime_target = _controlled_runtime_env_path(manifest)", candidate)

    def test_updated_baseline_is_idempotent(self):
        source = controlled(marketing(Path(__file__).with_name("main.py").read_text()))
        self.assertEqual(overlay(source), source)
        self.assertEqual(overlay(overlay(legacy_source())), overlay(legacy_source()))

    def test_unrelated_functions_are_preserved(self):
        before = legacy_source()
        after = overlay(before)
        def functions(source):
            return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef) and n.name != "_controlled_compose_base"}
        expected = functions(before)
        actual = functions(after)
        self.assertTrue(all(actual[name] == value for name, value in expected.items()))

    def test_unknown_compose_anchor_fails_closed(self):
        source = legacy_source().replace(
            "runtime_target, _ = _runtime_config(manifest)",
            "runtime_target, _ = unknown_runtime_helper(manifest)",
        )
        with self.assertRaisesRegex(ValueError, "compose_anchor_mismatch"):
            overlay(source)

    def test_conflicting_existing_tool_fails_closed(self):
        source = overlay(legacy_source()).replace(
            'return {"ok": False, "error": "expected_current_branch_required"}',
            'return {"ok": False, "error": "unexpected_conflict"}',
        )
        with self.assertRaisesRegex(ValueError, "existing_definition_conflict"):
            overlay(source)


class GuardedRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_tool_and_existing_clone_respect_publication_guard(self):
        source, guarded = independent_overlay(overlay(legacy_source()), "_load_manifest")
        self.assertIn("project_manifest_branch_configure", guarded)
        self.assertIn("project_clone", guarded)
        module = types.ModuleType("guarded_registry_test")
        exec(compile(source, "<guarded-registry>", "exec"), module.__dict__)
        policy = json.loads((GUARD_ROOT / "publication_sources.json").read_text())["conheca-sumare"]
        project = policy["production_project_ids"][0]
        module._load_manifest = lambda _: {"workspace_root": "/fixture-only", "repository": {"directory": "repository"}}
        def forbidden(*args, **kwargs):
            raise AssertionError("guarded test attempted operational access")
        module._manifest_path = forbidden
        module._run = forbidden
        module._audit = forbidden
        async with Client(module.mcp) as client:
            tools = await client.list_tools()
            self.assertEqual(sum(t.name == "project_manifest_branch_configure" for t in tools), 1)
            for name, args in (
                ("project_clone", {"project_id": project, "confirm": "EXECUTAR"}),
                ("project_manifest_branch_configure", {
                    "project_id": project, "branch": "fixture",
                    "expected_current_branch": "previous",
                    "expected_remote_commit": "a" * 40, "confirm": "EXECUTAR",
                }),
            ):
                result = await client.call_tool(name, args)
                data = json.loads("".join(c.text for c in result.content if hasattr(c, "text")))
                self.assertEqual(data["error"], "canonical_production_reconciliation_pending")


if __name__ == "__main__":
    unittest.main()
