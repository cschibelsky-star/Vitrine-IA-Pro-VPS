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
        shutil.copy2(path, path.with_name(f"{path.name}.backup-maintenance-{STAMP}"))


def ensure_after(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marcador não encontrado para {identity}: {marker!r}")
    return text.replace(marker, marker + addition, 1)


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f"Runtime MCP não encontrado: {ROOT}")

    target_module = ROOT / "maintenance_operations.py"
    shutil.copy2(SOURCE / "maintenance_operations.py", target_module)

    broker = ROOT / "ops_broker.py"
    compose = ROOT / "docker-compose.mcp.yml"
    if not broker.is_file() or not compose.is_file():
        raise RuntimeError("ops_broker.py ou docker-compose.mcp.yml ausente")

    backup(broker)
    backup(compose)

    broker_text = broker.read_text(encoding="utf-8")
    broker_text = ensure_after(
        broker_text,
        "from via_operations import router as via_operations_router\n",
        "from maintenance_operations import router as maintenance_router\n",
        "from maintenance_operations import router as maintenance_router",
    )
    broker_text = ensure_after(
        broker_text,
        "app.include_router(via_operations_router)\n",
        "app.include_router(maintenance_router)\n",
        "app.include_router(maintenance_router)",
    )
    broker.write_text(broker_text, encoding="utf-8")

    compose_text = compose.read_text(encoding="utf-8")
    env_marker = "      OPS_TIMEOUT: 1200\n"
    if "MCP_RUNTIME_ROOT:" not in compose_text:
        compose_text = ensure_after(
            compose_text,
            env_marker,
            "      MCP_RUNTIME_ROOT: /srv/connectors/vitrine-vps-mcp\n      MCP_MAINTENANCE_TIMEOUT: 1200\n",
            "MCP_RUNTIME_ROOT:",
        )

    docker_sock = "      - /var/run/docker.sock:/var/run/docker.sock\n"
    narrow_mount = "      - /srv/connectors/vitrine-vps-mcp:/srv/connectors/vitrine-vps-mcp:rw\n"
    if narrow_mount.strip() not in compose_text:
        compose_text = ensure_after(
            compose_text,
            docker_sock,
            narrow_mount,
            "/srv/connectors/vitrine-vps-mcp:/srv/connectors/vitrine-vps-mcp:rw",
        )
    compose.write_text(compose_text, encoding="utf-8")

    print("MCP_MAINTENANCE_BOOTSTRAP_PREPARED=SIM")
    print(f"BACKUP_STAMP={STAMP}")
    print("ACTIONS=status_mcp_connector,health_mcp_connector,restart_mcp_connector")


if __name__ == "__main__":
    main()
