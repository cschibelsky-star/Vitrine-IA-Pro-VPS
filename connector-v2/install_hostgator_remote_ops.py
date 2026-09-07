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


def ensure_after(text: str, anchor: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"anchor_missing:{identity}")
    return text.replace(anchor, anchor + addition, 1)


def ensure_before(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marker_missing:{identity}")
    return text.replace(marker, addition + marker, 1)


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

    backup(broker)
    broker_text = broker.read_text(encoding="utf-8")
    broker_import = "from hostgator_operations import router as hostgator_operations_router\n"
    if "hostgator_operations_router" not in broker_text:
        if "from tvsumare_operations import router as tvsumare_operations_router\n" in broker_text:
            broker_text = ensure_after(
                broker_text,
                "from tvsumare_operations import router as tvsumare_operations_router\n",
                broker_import,
                "hostgator_operations_router",
            )
        elif "from __future__ import annotations\n" in broker_text:
            broker_text = ensure_after(
                broker_text,
                "from __future__ import annotations\n",
                "\n" + broker_import,
                "hostgator_operations_router",
            )
        else:
            broker_text = broker_import + broker_text

    broker_include = "app.include_router(hostgator_operations_router)\n"
    if "include_router(hostgator_operations_router)" not in broker_text:
        if "app.include_router(tvsumare_operations_router)\n" in broker_text:
            broker_text = ensure_after(
                broker_text,
                "app.include_router(tvsumare_operations_router)\n",
                broker_include,
                "include_router(hostgator_operations_router)",
            )
        elif '\nif __name__ == "__main__":\n' in broker_text:
            broker_text = ensure_before(
                broker_text,
                '\nif __name__ == "__main__":\n',
                "\n" + broker_include,
                "include_router(hostgator_operations_router)",
            )
        else:
            broker_text = broker_text.rstrip() + "\n\n" + broker_include
    broker.write_text(broker_text, encoding="utf-8")

    backup(main_py)
    main_text = main_py.read_text(encoding="utf-8")
    tools_import = '''\nfrom hostgator_tools import (\n    hostgator_health as _hostgator_health,\n    hostgator_git_status as _hostgator_git_status,\n    hostgator_git_compare as _hostgator_git_compare,\n    hostgator_read_file as _hostgator_read_file,\n)\n'''
    if "from hostgator_tools import (" not in main_text:
        main_text = ensure_after(
            main_text,
            "from typing import Any\n",
            tools_import,
            "from hostgator_tools import (",
        )

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_health() -> dict[str, Any]:\n    return _hostgator_health()\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_git_status(root: str) -> dict[str, Any]:\n    return _hostgator_git_status(root)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_git_compare(root: str) -> dict[str, Any]:\n    return _hostgator_git_compare(root)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_read_file(root: str, path: str, max_bytes: int = 100000) -> dict[str, Any]:\n    return _hostgator_read_file(root, path, max_bytes)\n'''
    if "def hostgator_health()" not in main_text:
        main_text = ensure_before(
            main_text,
            '\nif __name__ == "__main__":\n',
            tools_block,
            "def hostgator_health()",
        )
    main_py.write_text(main_text, encoding="utf-8")

    check_broker = broker.read_text(encoding="utf-8")
    check_main = main_py.read_text(encoding="utf-8")
    if "hostgator_operations_router" not in check_broker or "include_router(hostgator_operations_router)" not in check_broker:
        raise SystemExit("hostgator_router_registration_failed")
    if "from hostgator_tools import (" not in check_main or "def hostgator_health()" not in check_main:
        raise SystemExit("hostgator_mcp_registration_failed")

    print("HOSTGATOR_REMOTE_OPS_INSTALLED=PASS")
    print(f"BACKUP_STAMP={STAMP}")


if __name__ == "__main__":
    main()
