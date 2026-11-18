import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "transport.py"
spec = importlib.util.spec_from_file_location("ssh_transport", MODULE)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


@pytest.mark.parametrize("operation", ["sh", "bash", "docker", "rm", "ssh", ""])
def test_arbitrary_operations_denied(operation):
    with pytest.raises(ValueError, match="operation_not_allowed"):
        module.validate_request(operation, module.PROJECT, module.SERVICE, "run_20261118")


@pytest.mark.parametrize("project,service", [
    ("production", module.SERVICE),
    (module.PROJECT, "another_service"),
])
def test_scope_denied(project, service):
    with pytest.raises(ValueError, match="scope_not_allowed"):
        module.validate_request("service_health", project, service, "run_20261118")


def test_deploy_requires_full_commit_sha():
    with pytest.raises(ValueError, match="invalid_commit_sha"):
        module.validate_request("deploy_service_commit_hml", module.PROJECT, module.SERVICE, "run_20261118", "fe3c689")


def test_read_operation_rejects_unexpected_sha():
    with pytest.raises(ValueError, match="unexpected_commit_sha"):
        module.validate_request("service_health", module.PROJECT, module.SERVICE, "run_20261118", "a" * 40)


def test_missing_identity_fails_before_network(tmp_path):
    config = module.SSHExecutorConfig("example.invalid", "executor", tmp_path / "id", tmp_path / "known_hosts")
    with pytest.raises(RuntimeError, match="ssh_identity_or_host_key_missing"):
        module.execute(config, "service_health", module.PROJECT, module.SERVICE, "run_20261118")
