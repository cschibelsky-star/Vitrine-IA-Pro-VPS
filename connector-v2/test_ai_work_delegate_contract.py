"""Offline contract checks for both candidate delegate interfaces."""
import unittest
from ai_work_delegate_contract import ContractRejected, normalize_mock_request


class ContractTests(unittest.TestCase):
    def base(self):
        return dict(task_id="mock-task-001", project="via", environment="hml",
                    scope="analysis", instruction="Inspect a unit test",
                    model="mock", budget_brl=0)

    def test_v5_mock(self):
        self.assertEqual(normalize_mock_request(self.base())["contract_version"], 1)

    def test_v2_mock(self):
        req = dict(experiment_id="mock-task-001", project="via", environment="hml",
                   scope="analysis", prompt="Inspect a unit test",
                   model="mock", max_charge_cents=0)
        self.assertEqual(normalize_mock_request(req)["task_id"], "mock-task-001")

    def test_paid_and_boolean_blocked(self):
        for bad in (True, 1, 0.01):
            with self.subTest(bad=bad), self.assertRaisesRegex(ContractRejected, "paid_calls_disabled"):
                normalize_mock_request({**self.base(), "budget_brl": bad})

    def test_production_blocked(self):
        with self.assertRaisesRegex(ContractRejected, "forbidden"):
            normalize_mock_request({**self.base(), "environment": "production"})

    def test_invalid_identifier_blocked(self):
        with self.assertRaisesRegex(ContractRejected, "invalid_task_id"):
            normalize_mock_request({**self.base(), "task_id": "../bad"})

    def test_invalid_instruction_blocked(self):
        with self.assertRaisesRegex(ContractRejected, "invalid_instruction"):
            normalize_mock_request({**self.base(), "instruction": 42})


if __name__ == "__main__":
    unittest.main()
