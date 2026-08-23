from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp"))
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.backup-hostgator-v4-{STAMP}"))


def ensure_line_after(text: str, anchor: str, line: str, label: str) -> str:
    if line in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"{label}: marcador nao encontrado")
    return text.replace(anchor, anchor + line, 1)


def ensure_block_before(text: str, marker: str, block: str, sentinel: str, label: str) -> str:
    if sentinel in text:
        return text
    if marker not in text:
        raise RuntimeError(f"{label}: marcador nao encontrado")
    return text.replace(marker, block + marker, 1)


def restore_oldest_project_manager_backup(path: Path) -> str:
    backups = sorted(
        ROOT.glob(f"{path.name}.backup-project-manager-*"),
        key=lambda candidate: candidate.stat().st_mtime,
    )
    if not backups:
        raise RuntimeError(f"backup project-manager nao encontrado para {path.name}")

    selected = backups[0]
    safety = ROOT / f"{path.name}.before-stability-recovery-{STAMP}"
    if path.exists():
        shutil.copy2(path, safety)
    shutil.copy2(selected, path)
    return selected.name


def disable_next_project_manager_install() -> None:
    installer = SOURCE.parent / "project-manager" / "install_project_manager.py"
    if not installer.is_file():
        raise RuntimeError("install_project_manager.py nao encontrado")

    installer.write_text(
        "from __future__ import annotations\n\n"
        "def main() -> None:\n"
        "    print('PROJECT_MANAGER_STABILITY_RECOVERY_NOOP=SIM')\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )


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
        target = ROOT / name
        restored[name] = restore_oldest_project_manager_backup(target)

    disable_next_project_manager_install()

    print("V4_STABILITY_RECOVERY_PREPARED=SIM")
    for name, source in restored.items():
        print(f"RESTORED_{name.replace('.', '_').upper()}={source}")
    print("PROJECT_MANAGER_REINSTALL_DISABLED_FOR_RECOVERY=SIM")
    print(f"RECOVERY_STAMP={STAMP}")


if __name__ == "__main__":
    main()
