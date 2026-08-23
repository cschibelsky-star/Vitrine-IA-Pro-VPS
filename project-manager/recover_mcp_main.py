from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp"))


def main() -> None:
    main_py = ROOT / "main.py"
    backups = sorted(
        ROOT.glob("main.py.backup-project-manager-*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not backups:
        raise SystemExit("MCP_MAIN_RECOVERY_BACKUP_NOT_FOUND")

    backup = backups[0]
    safety = ROOT / "main.py.before-recovery"
    if main_py.exists():
        shutil.copy2(main_py, safety)

    shutil.copy2(backup, main_py)
    print(f"MCP_MAIN_RECOVERED_FROM={backup.name}")
    print(f"MCP_MAIN_RECOVERY_SAFETY={safety.name if safety.exists() else 'none'}")


if __name__ == "__main__":
    main()
