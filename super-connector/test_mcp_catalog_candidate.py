"""Offline tests for the inert Super MCP packaging candidate.

Does not build an image, start a service, call Roteia or deploy anything.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
STAGE = "FROM hml_binding AS mcp_catalog_candidate"
EXPECTED_COPIES = {
    "super-connector/main_v2.py": "/opt/super-candidate/main.py",
    "super-connector/materialize_entrypoint.py": "/opt/super-candidate/materialize_entrypoint.py",
    "super-connector/foundation_entrypoint.py": "/opt/super-candidate/foundation_entrypoint.py",
    "super-connector/branding_entrypoint.py": "/opt/super-candidate/branding_entrypoint.py",
    "super-connector/foundation": "/opt/super-candidate/foundation",
    "super-connector/capability-manifest.json": "/opt/super-candidate/capability-manifest.json",
}


def _candidate_instructions():
    candidate = DOCKERFILE[DOCKERFILE.index(STAGE) :]
    return [
        line.strip()
        for line in candidate.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _mcp_run_is_main_guarded(tree, call):
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    node = call
    while node in parents:
        parent = parents[node]
        if (
            isinstance(parent, ast.If)
            and node in parent.body
            and isinstance(parent.test, ast.Compare)
            and isinstance(parent.test.left, ast.Name)
            and parent.test.left.id == "__name__"
            and len(parent.test.ops) == 1
            and isinstance(parent.test.ops[0], ast.Eq)
            and len(parent.test.comparators) == 1
            and isinstance(parent.test.comparators[0], ast.Constant)
            and parent.test.comparators[0].value == "__main__"
        ):
            return True
        node = parent
    return False


class CandidateImageSafetyTests(unittest.TestCase):
    def test_active_hml_stays_on_publication_guard_stage(self):
        self.assertIn("target: hml_binding", COMPOSE)
        self.assertNotIn("target: mcp_catalog_candidate", COMPOSE)
        self.assertIn("FROM vitrine-publication-guard-super:20261010 AS hml_binding", DOCKERFILE)

    def test_candidate_inherits_guard_but_is_not_live_runtime(self):
        instructions = _candidate_instructions()
        self.assertEqual(instructions[0], STAGE)
        self.assertEqual(sum(line.startswith("FROM ") for line in instructions), 1)
        for instruction in instructions[1:]:
            if instruction.startswith("COPY "):
                _, source, destination = instruction.split()
                self.assertIn(source, EXPECTED_COPIES)
                self.assertEqual(destination, EXPECTED_COPIES[source])
                self.assertTrue(destination.startswith("/opt/super-candidate/"))
            elif instruction.startswith("RUN "):
                self.assertEqual(
                    instruction,
                    "RUN python -m compileall -q /opt/super-candidate",
                    "the candidate must not run arbitrary shell or runtime commands",
                )
            else:
                self.fail(f"unexpected candidate runtime directive: {instruction}")

    def test_candidate_sources_compile_without_import_or_runtime_startup(self):
        copies = {}
        for instruction in _candidate_instructions()[1:]:
            if instruction.startswith("COPY "):
                _, source, destination = instruction.split()
                copies[source] = destination
                source_path = REPO_ROOT / source
                self.assertTrue(source_path.exists(), f"missing COPY source: {source}")
        self.assertEqual(copies, EXPECTED_COPIES)

        python_sources = []
        for source in copies:
            source_path = REPO_ROOT / source
            if source_path.is_file() and source_path.suffix == ".py":
                python_sources.append(source_path)
            elif source_path.is_dir():
                python_sources.extend(source_path.rglob("*.py"))
        self.assertTrue(python_sources)
        for source_path in python_sources:
            source = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_path))
            compile(tree, str(source_path), "exec")
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "mcp"
                ):
                    self.assertTrue(
                        _mcp_run_is_main_guarded(tree, node),
                        f"MCP runtime startup must be guarded in {source_path}",
                    )


if __name__ == "__main__":
    unittest.main()
