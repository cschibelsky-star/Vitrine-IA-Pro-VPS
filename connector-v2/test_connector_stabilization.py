from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "connector-v2" / "main_tvsumare_tools.py"
RUNTIME = ROOT / "connector-v2" / "connector_runtime.py"
OBSERVABILITY = ROOT / "connector-v2" / "connector_observability.py"
INSTALLER = ROOT / "connector-v2" / "install_connector_v2.py"
MANIFEST = ROOT / "project-manager" / "manifests" / "tvsumare.json"


def fail(message: str) -> None:
    raise SystemExit("CONNECTOR_STABILIZATION_TEST=FAIL " + message)


def test_installer_idempotency() -> None:
    with tempfile.TemporaryDirectory(prefix="connector-installer-") as temp:
        root = Path(temp)
        (root / "main.py").write_text(
            "from typing import Any\n\nfrom server import mcp\n\nif __name__ == \"__main__\":\n    pass\n",
            encoding="utf-8",
        )
        (root / "ops_broker.py").write_text(
            "from via_operations import router as via_operations_router\n"
            "app.include_router(via_operations_router)\n",
            encoding="utf-8",
        )
        (root / "Dockerfile").write_text("COPY server.py main.py ./\n", encoding="utf-8")
        (root / "docker-compose.mcp.yml").write_text(
            "services:\n"
            "  ops_broker:\n"
            "    environment:\n"
            "      OPS_TIMEOUT: 1200\n"
            "    volumes:\n"
            "      - /var/run/docker.sock:/var/run/docker.sock\n",
            encoding="utf-8",
        )
        env = {**os.environ, "CONNECTOR_ROOT": str(root)}
        for _ in range(2):
            subprocess.run([sys.executable, str(INSTALLER)], check=True, capture_output=True, text=True, env=env)

        main_text = (root / "main.py").read_text(encoding="utf-8")
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        checks = {
            "middleware": main_text.count("mcp.add_middleware(SafeToolCallLoggingMiddleware())"),
            "connector_health": main_text.count("def connector_health() -> dict[str, Any]:"),
            "project_context": main_text.count("def project_context(project_id: str) -> dict[str, Any]:"),
            "runtime_image": dockerfile.count("connector_runtime.py"),
            "observability_image": dockerfile.count("connector_observability.py"),
        }
        if any(count != 1 for count in checks.values()):
            fail(f"instalador não idempotente: {checks}")
        if not (root / "connector_observability.py").is_file():
            fail("instrumentação não copiada")


def main() -> None:
    tools = TOOLS.read_text(encoding="utf-8")
    tools_tree = ast.parse(tools)
    for node in ast.walk(tools_tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and "fastmcp" in ast.unparse(node).lower():
            fail("tvsumare helper ainda importa FastMCP")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any("mcp.tool" in ast.unparse(decorator) for decorator in node.decorator_list):
                fail("tvsumare helper ainda registra MCP")

    runtime = RUNTIME.read_text(encoding="utf-8")
    if 'CONNECTOR_ID = "vitrine_ops"' not in runtime:
        fail("connector_id tecnico ausente")
    if "def connector_health()" not in runtime or "def project_context(" not in runtime:
        fail("health/context ausentes")

    observability = OBSERVABILITY.read_text(encoding="utf-8")
    for event in ("TOOL_CALL", "TOOL_RESULT", "TOOL_ERROR"):
        if event not in observability:
            fail(f"instrumentação ausente: {event}")
    for forbidden in ("context.message.arguments", "Authorization", "OPS_BROKER_TOKEN", "str(exc)", "exc_info=True"):
        if forbidden in observability:
            fail(f"instrumentação pode registrar dado sensível: {forbidden}")

    installer = INSTALLER.read_text(encoding="utf-8")
    required_installer_fragments = [
        "shutil.copy2(SOURCE / 'connector_runtime.py'",
        "shutil.copy2(SOURCE / 'connector_observability.py'",
        "from connector_runtime import (",
        "mcp.add_middleware(SafeToolCallLoggingMiddleware())",
        "def connector_health()",
        "def project_context(project_id: str)",
    ]
    for fragment in required_installer_fragments:
        if fragment not in installer:
            fail(f"instalador não integra runtime: {fragment}")

    # Só o main.py instalado pode registrar as ferramentas. Helpers permanecem funções puras.
    if installer.count('def connector_health() -> dict[str, Any]:') != 1:
        fail("connector_health deve ser registrado uma única vez")
    if installer.count('def project_context(project_id: str) -> dict[str, Any]:') != 1:
        fail("project_context deve ser registrado uma única vez")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checks = {
        "workspace_root": "/srv/tvsumare",
        "repository.directory": "repository",
        "repository.branch": "feature/tvsumare-boletim-social",
        "docker.compose_file": "docker-compose.vps.yml",
        "docker.service": "web",
        "backup_root": "/srv/backups/tvsumare",
    }
    actual = {
        "workspace_root": manifest.get("workspace_root"),
        "repository.directory": manifest.get("repository", {}).get("directory"),
        "repository.branch": manifest.get("repository", {}).get("branch"),
        "docker.compose_file": manifest.get("docker", {}).get("compose_file"),
        "docker.service": manifest.get("docker", {}).get("service"),
        "backup_root": manifest.get("backup_root"),
    }
    for key, expected in checks.items():
        if actual.get(key) != expected:
            fail(f"{key}={actual.get(key)!r} esperado={expected!r}")

    test_installer_idempotency()

    print("CONNECTOR_STABILIZATION_TEST=PASS")
    print("CONNECTOR_REGISTRY_TEST=PASS")
    print("SAFE_INSTRUMENTATION_TEST=PASS")
    print("INSTALLER_IDEMPOTENCY_TEST=PASS")


if __name__ == "__main__":
    main()
