from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp"))
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")


def restore_oldest_project_manager_backup(path: Path) -> str:
    backups = sorted(
        ROOT.glob(f"{path.name}.backup-project-manager-*"),
        key=lambda candidate: candidate.stat().st_mtime,
    )
    if not backups:
        raise RuntimeError(f"backup project-manager nao encontrado para {path.name}")
    selected = backups[0]
    safety = ROOT / f"{path.name}.before-diagnostic-{STAMP}"
    if path.exists():
        shutil.copy2(path, safety)
    shutil.copy2(selected, path)
    return selected.name


def disable_next_project_manager_install() -> None:
    installer = SOURCE.parent / "project-manager" / "install_project_manager.py"
    installer.write_text(
        "from __future__ import annotations\n\n"
        "def main() -> None:\n"
        "    print('PROJECT_MANAGER_DIAGNOSTIC_NOOP=SIM')\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )


def instrument_connector_output() -> None:
    override = ROOT / "docker-compose.connector-v2.override.yml"
    text = override.read_text(encoding="utf-8")
    service_marker = "  vps_mcp_connector:\n"
    if service_marker not in text:
        raise RuntimeError("vps_mcp_connector nao encontrado no override")

    volume_line = "      - /srv/projects/vitrine-vps-ops/repository/storage/app/factory/vps-ops:/runtime-diagnostics:rw\n"
    if volume_line not in text:
        volumes_marker = "    volumes:\n"
        service_start = text.index(service_marker)
        volumes_at = text.find(volumes_marker, service_start)
        if volumes_at == -1:
            raise RuntimeError("volumes do vps_mcp_connector nao encontrados")
        insert_at = volumes_at + len(volumes_marker)
        text = text[:insert_at] + volume_line + text[insert_at:]

    command_block = (
        "    command:\n"
        "      - sh\n"
        "      - -lc\n"
        "      - >-\n"
        "        rm -f /runtime-diagnostics/mcp-startup.txt;\n"
        "        python main.py > /runtime-diagnostics/mcp-startup.txt 2>&1;\n"
        "        rc=$$?;\n"
        "        echo EXIT_CODE=$$rc >> /runtime-diagnostics/mcp-startup.txt;\n"
        "        sleep 60;\n"
        "        exit $$rc\n"
    )
    if "    command:\n      - sh\n      - -lc\n" not in text[service_start:]:
        text = text[:service_start + len(service_marker)] + command_block + text[service_start + len(service_marker):]

    override.write_text(text, encoding="utf-8")


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f"Raiz do conector nao encontrada: {ROOT}")

    restored = {}
    for name in (
        "main.py",
        "ops_broker.py",
        "Dockerfile",
        "docker-compose.connector-v2.override.yml",
    ):
        restored[name] = restore_oldest_project_manager_backup(ROOT / name)

    disable_next_project_manager_install()
    instrument_connector_output()

    print("V4_DIAGNOSTIC_RECOVERY_PREPARED=SIM")
    for name, source in restored.items():
        print(f"RESTORED_{name.replace('.', '_').upper()}={source}")
    print("MCP_STARTUP_CAPTURE=ENABLED")
    print(f"RECOVERY_STAMP={STAMP}")


if __name__ == "__main__":
    main()
