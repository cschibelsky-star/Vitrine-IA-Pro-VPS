import re
import unittest
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "deploy-super-hml.yml"
)


class DeploySuperHmlWorkflowTests(unittest.TestCase):
    def test_expected_sha_input_is_passed_safely_to_validation_step(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        step = workflow.split(
            "      - name: Validate checked-out source\n", 1
        )[1].split("\n      - name:", 1)[0]
        run_script = step.split("        run: |\n", 1)[1]

        self.assertRegex(
            step,
            re.compile(
                r"(?m)^\s+EXPECTED_SHA_INPUT:\s*"
                r"\$\{\{\s*inputs\.expected_sha\s*\}\}\s*$"
            ),
        )
        self.assertNotIn("${{ inputs.expected_sha }}", run_script)
        self.assertIn('EXPECTED="$EXPECTED_SHA_INPUT"', run_script)


if __name__ == "__main__":
    unittest.main()
