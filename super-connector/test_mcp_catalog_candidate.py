"""Offline tests for the inert Super MCP packaging candidate.

Does not build an image, start a service, call Roteia or deploy anything.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


class CandidateImageSafetyTests(unittest.TestCase):
    def test_active_hml_stays_on_publication_guard_stage(self):
        self.assertIn("target: hml_binding", COMPOSE)
        self.assertNotIn("target: mcp_catalog_candidate", COMPOSE)
        self.assertIn("FROM vitrine-publication-guard-super:20261010 AS hml_binding", DOCKERFILE)

    def test_candidate_inherits_guard_but_is_not_live_runtime(self):
        candidate = DOCKERFILE[
            DOCKERFILE.index("FROM hml_binding AS mcp_catalog_candidate") :
        ]
        instructions = [
            line.strip()
            for line in candidate.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(instructions[0], "FROM hml_binding AS mcp_catalog_candidate")
        self.assertEqual(sum(line.startswith("FROM ") for line in instructions), 1)
        for instruction in instructions[1:]:
            if instruction.startswith("COPY "):
                _, _, destination = instruction.split(maxsplit=2)
                self.assertTrue(
                    destination.startswith("/opt/super-candidate/"),
                    f"candidate content must stay outside the live app: {instruction}",
                )
            elif instruction.startswith("RUN "):
                self.assertEqual(
                    instruction,
                    "RUN python -m compileall -q /opt/super-candidate",
                    "the candidate must not run arbitrary shell or runtime commands",
                )
            else:
                self.fail(f"unexpected candidate runtime directive: {instruction}")
        self.assertNotIn("/app/branding_entrypoint.py", candidate)
        self.assertNotIn("ROTEIA_API_KEY", candidate)

    def test_catalog_is_staged_outside_app_and_syntax_compiled(self):
        candidate = DOCKERFILE.split("FROM hml_binding AS mcp_catalog_candidate", 1)[1]
        for source, target in (
            ("main_v2.py", "main.py"),
            ("materialize_entrypoint.py", "materialize_entrypoint.py"),
            ("foundation_entrypoint.py", "foundation_entrypoint.py"),
            ("branding_entrypoint.py", "branding_entrypoint.py"),
            ("foundation", "foundation"),
            ("capability-manifest.json", "capability-manifest.json"),
        ):
            self.assertIn(f"COPY super-connector/{source} /opt/super-candidate/{target}", candidate)
        self.assertIn("RUN python -m compileall -q /opt/super-candidate", candidate)
        self.assertNotIn("COPY super-connector/main_v2.py /app/main.py", candidate)


if __name__ == "__main__":
    unittest.main()
