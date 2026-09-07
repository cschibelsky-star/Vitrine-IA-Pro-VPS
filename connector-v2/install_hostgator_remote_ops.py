from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp")).resolve()
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.backup-hostgator-v4-{STAMP}"))


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f"runtime_missing:{ROOT}")

    for name in ("hostgator_operations.py", "hostgator_tools.py"):
        source = SOURCE / name
        target = ROOT / name
        if not source.is_file():
            raise SystemExit(f"source_missing:{name}")
        backup(target)
        shutil.copy2(source, target)

    broker = ROOT / "ops_broker.py"
    main_py = ROOT / "main.py"
    if not broker.is_file() or not main_py.is_file():
        raise SystemExit("runtime_entrypoints_missing")

    broker_text = broker.read_text(encoding="utf-8")
    main_text = main_py.read_text(encoding="utf-8")
    if "hostgator_operations" not in broker_text and "/hostgator" not in broker_text:
        raise SystemExit("hostgator_router_registration_missing")
    if "hostgator_tools" not in main_text and "hostgator_health" not in main_text:
        raise SystemExit("hostgator_mcp_registration_missing")

    print("HOSTGATOR_REMOTE_OPS_INSTALLED=PASS")
    print(f"BACKUP_STAMP={STAMP}")


if __name__ == "__main__":
    main()
