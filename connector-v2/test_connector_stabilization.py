from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "connector-v2" / "main_tvsumare_tools.py"
RUNTIME = ROOT / "connector-v2" / "connector_runtime.py"
INSTALLER = ROOT / "connector-v2" / "install_connector_v2.py"
MANIFEST = ROOT / "project-manager" / "manifests" / "tvsumare.json"


def fail(message: str) -> None:
    raise SystemExit("CONNECTOR_STABILIZATION_TEST=FAIL " + message)


def main() -> None:
    tools = TOOLS.read_text(encoding="utf-8")
    if "FastMCP" in tools or "@mcp.tool" in tools:
        fail("tvsumare helper ainda registra MCP")

    runtime = RUNTIME.read_text(encoding="utf-8")
    if 'CONNECTOR_ID = "vitrine_ops"' not in runtime:
        fail("connector_id tecnico ausente")
    if "def connector_health()" not in runtime or "def project_context(" not in runtime:
        fail("health/context ausentes")

    installer = INSTALLER.read_text(encoding="utf-8")
    required_installer_fragments = [
        "shutil.copy2(SOURCE / 'connector_runtime.py'",
        "from connector_runtime import (",
        "def connector_health()",
        "def project_context(project_id: str)",
    ]
    for fragment in required_installer_fragments:
        if fragment not in installer:
            fail(f"instalador não integra runtime: {fragment}")

    # Só o main.py instalado pode registrar as ferramentas. Helpers permanecem funções puras.
    if installer.count('def connector_health()') != 1:
        fail("connector_health deve ser registrado uma única vez")
    if installer.count('def project_context(project_id: str)') != 1:
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

    print("CONNECTOR_STABILIZATION_TEST=PASS")
    print("CONNECTOR_REGISTRY_TEST=PASS")


if __name__ == "__main__":
    main()
