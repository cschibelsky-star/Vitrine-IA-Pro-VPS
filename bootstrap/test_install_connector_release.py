from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "bootstrap" / "install_connector_release.py"
FILE_OPERATIONS_TEST = ROOT / "project-manager" / "test_project_file_operations.py"
FILE_OPERATIONS_DOMAIN = ROOT / "project-manager" / "project_file_operations.py"


def main() -> None:
    text = RELEASE.read_text(encoding="utf-8")
    ast.parse(text)

    forbidden = [
        "main_tool_registry",
        "import main;",
        "connector_health_runtime",
        "project_context_runtime",
        "'docker', 'exec', 'vitrine_vps_mcp_connector'",
        "compose_command('config')",
    ]
    for fragment in forbidden:
        assert fragment not in text, f"obsolete import-based gate returned: {fragment}"

    required = [
        "label='mcp_protocol_registry'",
        "compose_command('config', '--quiet')",
        "'docker', 'run', '--rm'",
        "'--network', probe_network",
        "'--entrypoint', 'python'",
        "'--url', 'http://vps_mcp_connector:8765/mcp'",
        "'/app/probe_streamable_http.py'",
        "'--catalog-only'",
        "'--require-tool', 'project_deploy'",
        "'--require-tool', 'connector_health'",
        "'--require-tool', 'project_context'",
        "'--require-tool', 'project_write_file'",
        "'--require-tool', 'project_php_lint'",
        "'source_project_file_operations_test'",
        "'project-manager' / 'project_file_operations.py'",
        "CONNECTOR_ROOT / 'project_file_operations.py'",
        "restore_backup(backup)",
    ]
    for fragment in required:
        assert fragment in text, f"protocol release gate incomplete: {fragment}"

    test_text = FILE_OPERATIONS_TEST.read_text(encoding="utf-8")
    domain_text = FILE_OPERATIONS_DOMAIN.read_text(encoding="utf-8")
    ast.parse(test_text)
    ast.parse(domain_text)
    for dependency in ("fastapi", "pydantic"):
        assert dependency not in test_text
        assert dependency not in domain_text

    spec = importlib.util.spec_from_file_location("release_under_test", RELEASE)
    assert spec and spec.loader
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    captured_commands: list[list[str]] = []

    def fake_capture(command: list[str], _cwd: Path | None = None) -> str:
        captured_commands.append(command)
        if command[:2] == ["docker", "compose"]:
            return "container-id"
        if "{{.Config.Image}}" in command:
            return "local/connector:test"
        return "project_default\nvitrine_mcp_internal\n"

    release.capture = fake_capture
    image, network = release.resolve_mcp_probe_runtime()
    assert image == "local/connector:test"
    assert network == "vitrine_mcp_internal"
    assert any(command[-2:] == ["-q", "vps_mcp_connector"] for command in captured_commands)

    print("RELEASE_PROTOCOL_GATE_TEST=PASS")
    print("NO_DOCKER_EXEC_GATE_PASS")
    print("NO_SECRET_COMPOSE_OUTPUT_PASS")
    print("SOURCE_FILE_OPERATIONS_STDLIB_TEST=PASS")
    print("NO_IMPORT_MAIN_GATE_TEST=PASS")
    print("ROLLBACK_PRESERVED_TEST=PASS")


if __name__ == "__main__":
    main()
