from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp")).resolve()
BROKER = ROOT / "ops_broker.py"
STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
IMPORT_LINE = "from tvsumare_operations import router as tvsumare_operations_router\n"
INCLUDE_LINE = "app.include_router(tvsumare_operations_router)\n"


def insert_after_future(text: str, line: str) -> str:
    marker = "from __future__ import annotations\n"
    if line in text:
        return text
    if marker in text:
        return text.replace(marker, marker + "\n" + line, 1)
    return line + text


def insert_router_include(text: str, line: str) -> str:
    if line in text:
        return text
    main_marker = '\nif __name__ == "__main__":\n'
    if main_marker in text:
        return text.replace(main_marker, "\n" + line + main_marker, 1)
    return text.rstrip() + "\n\n" + line


def main() -> None:
    if not BROKER.is_file():
        raise SystemExit(f"ops_broker_missing:{BROKER}")

    backup = BROKER.with_name(f"ops_broker.py.backup-v4-router-repair-{STAMP}")
    shutil.copy2(BROKER, backup)

    text = BROKER.read_text(encoding="utf-8")
    text = insert_after_future(text, IMPORT_LINE)
    text = insert_router_include(text, INCLUDE_LINE)
    BROKER.write_text(text, encoding="utf-8")

    check = BROKER.read_text(encoding="utf-8")
    if IMPORT_LINE not in check or INCLUDE_LINE not in check:
        raise SystemExit("router_repair_validation_failed")

    print(f"V4_ROUTER_REPAIR=PASS backup={backup}")


if __name__ == "__main__":
    main()
