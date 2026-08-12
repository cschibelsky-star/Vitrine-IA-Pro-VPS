from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "project-manager" / "install_project_manager.py"


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _write_fixture(connector_root: Path) -> None:
    (connector_root / "main.py").write_text(
        "from typing import Any\n\n"
        "from tvsumare_migration_tools import (\n    placeholder,\n)\n\n"
        "if __name__ == \"__main__\":\n    pass\n",
        encoding="utf-8",
    )
    (connector_root / "ops_broker.py").write_text(
        "from tvsumare_migration_operations import router as tvsumare_migration_router\n\n"
        "app.include_router(tvsumare_migration_router)\n",
        encoding="utf-8",
    )
    (connector_root / "Dockerfile").write_text(
        "COPY server.py main.py ./\n",
        encoding="utf-8",
    )
    (connector_root / "docker-compose.mcp.yml").write_text(
        "services:\n"
        "  ops_broker:\n"
        "    image: test-ops-broker\n"
        "  vps_mcp_connector:\n"
        "    image: test-connector\n",
        encoding="utf-8",
    )
    (connector_root / "docker-compose.connector-v2.override.yml").write_text(
        "services:\n"
        "  ops_broker:\n"
        "    volumes:\n"
        "      - /existing/ops:/existing/ops:rw\n"
        "    environment:\n"
        "      EXISTING_OPS: unchanged\n"
        "  vps_mcp_connector:\n"
        "    volumes:\n"
        "      - /existing/mcp:/existing/mcp:ro\n"
        "    environment:\n"
        "      EXISTING_MCP: unchanged\n"
        "networks:\n"
        "  ops_broker:\n"
        "    external: true\n",
        encoding="utf-8",
    )


def _parse_unique(path: Path) -> dict[str, Any]:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)


def _docker_compose_config(connector_root: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        print("DOCKER_COMPOSE_CONFIG=SKIP docker_unavailable")
        return
    result = subprocess.run(
        [
            docker,
            "compose",
            "-f",
            "docker-compose.mcp.yml",
            "-f",
            "docker-compose.connector-v2.override.yml",
            "config",
        ],
        cwd=connector_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"docker compose config failed: {result.stderr}")
    print("DOCKER_COMPOSE_CONFIG=PASS")


def _assert_compose(compose_path: Path) -> None:
    text = compose_path.read_text(encoding="utf-8")
    data = _parse_unique(compose_path)
    services = data["services"]
    ops = services["ops_broker"]
    mcp = services["vps_mcp_connector"]

    assert text.count("    volumes:") == 2
    assert text.count("    environment:") == 2
    assert ops["environment"]["EXISTING_OPS"] == "unchanged"
    assert ops["environment"]["PROJECT_MANIFEST_ROOT"] == "/app/project-manifests"
    assert ops["environment"]["PROJECT_WORKSPACE_ROOTS"] == "/srv/tvsumare,/srv/projects"
    assert ops["environment"]["OPS_AUDIT_LOG"] == "/var/log/vitrine-ops/audit.jsonl"
    assert ops["volumes"] == [
        "/var/log/vitrine-ops:/var/log/vitrine-ops:rw",
        "/srv/projects:/srv/projects:rw",
        "/existing/ops:/existing/ops:rw",
    ]
    assert mcp["environment"] == {"EXISTING_MCP": "unchanged"}
    assert mcp["volumes"] == [
        "/srv/projects:/host/projects:ro",
        "/existing/mcp:/existing/mcp:ro",
    ]
    assert data["networks"] == {"ops_broker": {"external": True}}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="project-manager-installer-") as temp:
        connector_root = Path(temp)
        _write_fixture(connector_root)
        env = {**os.environ, "CONNECTOR_ROOT": str(connector_root)}
        snapshots: list[tuple[bytes, bytes]] = []

        for _ in range(2):
            subprocess.run(
                [sys.executable, str(INSTALLER)],
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            compose_path = connector_root / "docker-compose.connector-v2.override.yml"
            _assert_compose(compose_path)
            _docker_compose_config(connector_root)
            main_path = connector_root / "main.py"
            main_text = main_path.read_text(encoding="utf-8")
            assert main_text.count("project_write_file as _project_write_file,") == 1
            assert main_text.count("project_php_lint as _project_php_lint,") == 1
            assert main_text.count("def project_write_file(") == 1
            assert main_text.count("def project_php_lint(") == 1
            assert '"destructiveHint": True' in main_text
            tools_text = (connector_root / "project_manager_tools.py").read_text(encoding="utf-8")
            assert "def project_write_file(" in tools_text
            assert "def project_php_lint(" in tools_text
            assert (connector_root / "project_file_operations.py").is_file()
            assert "project_file_operations.py" in (connector_root / "Dockerfile").read_text(encoding="utf-8")
            snapshots.append((compose_path.read_bytes(), main_path.read_bytes()))

        assert snapshots[0] == snapshots[1]
        print("PROJECT_MANAGER_COMPOSE_REGRESSION_TEST=PASS")
        print("PROJECT_MANAGER_SAFE_FILE_TOOLS_TEST=PASS")
        print("PROJECT_MANAGER_INSTALLER_IDEMPOTENCY_TEST=PASS")


if __name__ == "__main__":
    main()
