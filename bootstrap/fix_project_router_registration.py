from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp")).resolve()
TARGET = ROOT / "ops_broker.py"
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")

ROUTERS = (
    "project_manager_router",
    "project_read_router",
    "project_shared_router",
    "project_explicit_router",
    "project_deployment_router",
)


def main() -> None:
    if not TARGET.is_file():
        raise SystemExit(f"ops_broker_missing:{TARGET}")

    backup = TARGET.with_name(f"{TARGET.name}.backup-router-order-{STAMP}")
    shutil.copy2(TARGET, backup)

    text = TARGET.read_text(encoding="utf-8")

    for router in ROUTERS:
        import_token = f" as {router}"
        if import_token not in text:
            raise RuntimeError(f"router_import_missing:{router}")
        text = re.sub(
            rf"^app\.include_router\({re.escape(router)}\)\s*$\n?",
            "",
            text,
            flags=re.MULTILINE,
        )

    block = "\n\n# Project Manager V4 routers must bind to the final FastAPI app instance.\n"
    block += "".join(f"app.include_router({router})\n" for router in ROUTERS)

    text = text.rstrip() + block + "\n"
    TARGET.write_text(text, encoding="utf-8")

    print("PROJECT_ROUTER_REGISTRATION_FIXED=PASS")
    print(f"BACKUP={backup}")


if __name__ == "__main__":
    main()
