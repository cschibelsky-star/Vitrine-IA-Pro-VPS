import unittest
from unittest.mock import patch, call
import maintenance_broker as broker

CID = "a" * 64

class MaintenanceTests(unittest.TestCase):
    @patch.object(broker, "docker")
    def test_status(self, docker):
        docker.return_value = f"{CID}|{broker.PROJECT}|{broker.SERVICE}|running"
        result = broker.operation({"operation": "candidate_status"})
        self.assertTrue(result["ok"])
        self.assertEqual(docker.call_count, 2)
        self.assertTrue(all(c.args[0] == "inspect" for c in docker.call_args_list))

    @patch.object(broker, "docker")
    def test_restart(self, docker):
        state = f"{CID}|{broker.PROJECT}|{broker.SERVICE}|running"
        docker.side_effect = [state, CID, state]
        self.assertTrue(broker.operation({"operation": "candidate_restart"})["ok"])
        self.assertEqual(docker.call_args_list[1], call("restart", "--time", "10", CID))

    @patch.object(broker, "docker")
    def test_denied(self, docker):
        for request in ({"operation": "shell"}, {"operation": "deploy"}, {"operation": "candidate_restart", "target": "other"}, [], {"operation": None}):
            with self.assertRaises((ValueError, PermissionError)):
                broker.operation(request)
        docker.assert_not_called()

    @patch.object(broker, "docker")
    def test_wrong_project(self, docker):
        docker.return_value = f"{CID}|other|{broker.SERVICE}|running"
        with self.assertRaises(PermissionError):
            broker.operation({"operation": "candidate_restart"})
        self.assertEqual(docker.call_count, 1)

    @patch.object(broker, "docker")
    def test_changed_target(self, docker):
        docker.side_effect = [f"{CID}|{broker.PROJECT}|{broker.SERVICE}|running", CID, f"{'b'*64}|{broker.PROJECT}|{broker.SERVICE}|running"]
        with self.assertRaises(RuntimeError):
            broker.operation({"operation": "candidate_restart"})

if __name__ == "__main__":
    unittest.main()
