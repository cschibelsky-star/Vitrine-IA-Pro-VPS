import unittest
from unittest.mock import patch
from types import SimpleNamespace

import maintenance_broker as broker
import maintenance_client as client


class PilotTests(unittest.TestCase):
    def test_catalog_only_advertises_supported_hml_operations(self):
        result = broker.operation({"operation": "hml_project_catalog"})
        projects = {p["project_id"]: p for p in result["projects"]}
        self.assertEqual(set(projects), {"assessor-online-pr137-current-hml", "cockpit-admin-v1-hml"})
        for project in projects.values():
            self.assertEqual(project["environment"], "homologation")
            expected = ["project_hml_snapshot", "project_hml_release_preflight"]
            if project["project_id"] == "assessor-online-pr137-current-hml":
                expected.append("project_hml_database_backup")
            self.assertEqual(project["operations"], expected)

    @patch.object(broker.assessor_snapshot, "create_snapshot", return_value={"verified": True})
    def test_cockpit_target_and_paths_are_fixed_on_the_host(self, snapshot):
        result = broker.operation({"operation": "project_hml_snapshot", "project_id": "cockpit-admin-v1-hml"})
        self.assertEqual(result["target"], "cockpit-admin-v1-hml")
        self.assertEqual(str(snapshot.call_args.kwargs["root"]), "/srv/projects/cockpit-admin-v1-hml/repository")
        self.assertEqual(snapshot.call_args.kwargs["paths"], ("config/cockpit-applications.php", "routes/cockpit.php"))

    @patch.object(broker.assessor_snapshot, "create_snapshot")
    def test_rejects_unknown_project_and_arbitrary_paths(self, snapshot):
        for data in (
            {"operation": "project_hml_snapshot", "project_id": "production"},
            {"operation": "project_hml_snapshot", "project_id": "../tvsumare"},
            {"operation": "project_hml_snapshot", "project_id": "cockpit-admin-v1-hml", "path": "/etc"},
            {"operation": "project_hml_snapshot", "project_id": []},
        ):
            with self.assertRaises((PermissionError, ValueError)):
                broker.operation(data)
        snapshot.assert_not_called()

    def test_catalog_is_read_only_snapshot_requires_write_and_confirmation(self):
        token = SimpleNamespace(subject="operator", scopes=["projects:read"])
        client.authorize(token, "hml_project_catalog", "operator", True)
        with self.assertRaises(PermissionError):
            client.authorize(token, "project_hml_snapshot", "operator", True, "EXECUTAR")
        token.scopes.append("projects:write")
        with self.assertRaises(PermissionError):
            client.authorize(token, "project_hml_snapshot", "operator", True)
        client.authorize(token, "project_hml_snapshot", "operator", True, "EXECUTAR")
