from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp-main"))
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.backup-via-prerequisite-{STAMP}"))


def ensure_after(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marker_not_found:{identity}:{marker!r}")
    return text.replace(marker, marker + addition, 1)


def ensure_before(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marker_not_found:{identity}:{marker!r}")
    return text.replace(marker, addition + marker, 1)


def patch_dockerfile(path: Path) -> None:
    backup(path)
    text = path.read_text(encoding="utf-8")
    if "via_operations.py" in text:
        return
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("COPY ") and line.endswith(" ./"):
            parts = line.split()
            if "via_operations.py" not in parts:
                lines[index] = line[:-3] + " via_operations.py ./"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise RuntimeError("dockerfile_copy_marker_not_found")


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f"connector_root_not_found:{ROOT}")

    source_module = SOURCE / "via_operations.py"
    if not source_module.is_file():
        raise SystemExit(f"source_module_not_found:{source_module}")

    target_module = ROOT / "via_operations.py"
    if target_module.exists():
        backup(target_module)
    shutil.copy2(source_module, target_module)

    ops = ROOT / "ops_broker.py"
    backup(ops)
    text = ops.read_text(encoding="utf-8")

    import_marker = "from pydantic import BaseModel, Field\n"
    text = ensure_after(
        text,
        import_marker,
        "from via_operations import router as via_operations_router\n",
        "from via_operations import router as via_operations_router",
    )

    include_marker = "app = FastAPI(title=\"Vitrine IA Pro Operations Broker\", docs_url=None, redoc_url=None)\n"
    text = ensure_after(
        text,
        include_marker,
        "app.include_router(via_operations_router)\n",
        "app.include_router(via_operations_router)",
    )

    ops.write_text(text, encoding="utf-8")
    patch_dockerfile(ROOT / "Dockerfile")

    print("VIA_OPERATIONS_PREREQUISITE_INSTALLED=SIM")
    print(f"CONNECTOR_ROOT={ROOT}")
    print(f"BACKUP_STAMP={STAMP}")


if __name__ == "__main__":
    main()
