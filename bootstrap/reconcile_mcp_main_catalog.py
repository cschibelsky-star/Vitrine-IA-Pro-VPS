from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp-main")).resolve()
REPO = Path(__file__).resolve().parent.parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP_ROOT = Path("/srv/vitrine/backups/mcp-main-catalog") / STAMP


def run(command: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
    print("+", " ".join(command), flush=True)
    proc = subprocess.run(command, cwd=str(cwd or REPO), env=env, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(command)}")


def require(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"required path missing: {path}")


def preserve_runtime() -> None:
    BACKUP_ROOT.parent.mkdir(parents=True, exist_ok=True)
    if BACKUP_ROOT.exists():
        raise RuntimeError(f"backup target already exists: {BACKUP_ROOT}")
    shutil.copytree(ROOT, BACKUP_ROOT, symlinks=True)
    print(f"BACKUP={BACKUP_ROOT}", flush=True)


def assert_marker(path: Path, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        raise RuntimeError(f"marker missing in {path.name}: {marker}")


def main() -> int:
    if not ROOT.is_dir():
        raise SystemExit(f"connector root not found: {ROOT}")

    for item in ("main.py", "ops_broker.py", "Dockerfile", "docker-compose.mcp.yml", "via_operations.py", "hostgator_operations.py", "hostgator_tools.py"):
        require(ROOT / item)

    # Current HostGator integration must be preserved, not reinstalled by the historical diagnostic script.
    assert_marker(ROOT / "ops_broker.py", "from hostgator_operations import router as hostgator_router")
    assert_marker(ROOT / "ops_broker.py", "app.include_router(hostgator_router)")
    assert_marker(ROOT / "main.py", "hostgator_health")

    preserve_runtime()

    env = dict(os.environ)
    env["CONNECTOR_ROOT"] = str(ROOT)

    # Prerequisite is idempotent and ensures the marker expected by stabilization v2.
    run([sys.executable, "connector-v2/install_via_operations_prerequisite.py"], env=env)

    # Apply stabilization/runtime layer.
    run([sys.executable, "connector-v2/install_connector_v2.py"], env=env)

    # Apply the complete project manager registry layer.
    run([sys.executable, "project-manager/install_project_manager.py"], env=env)

    # HostGator must still be registered after both installers.
    assert_marker(ROOT / "ops_broker.py", "from hostgator_operations import router as hostgator_router")
    assert_marker(ROOT / "ops_broker.py", "app.include_router(hostgator_router)")
    assert_marker(ROOT / "main.py", "hostgator_health")

    compile_targets = [
        "main.py",
        "ops_broker.py",
        "via_operations.py",
        "hostgator_operations.py",
        "hostgator_tools.py",
        "connector_runtime.py",
        "connector_observability.py",
        "tvsumare_operations.py",
        "tvsumare_tools.py",
        "project_manager_operations.py",
        "project_file_operations.py",
        "project_manager_tools.py",
        "project_deployment_engine.py",
        "project_read_operations.py",
        "project_shared_operations.py",
        "project_explicit_operations.py",
    ]
    run([sys.executable, "-m", "py_compile", *[str(ROOT / name) for name in compile_targets]])

    # Validate registry markers before any Docker rebuild.
    for marker in (
        "def connector_health()",
        "def project_context(",
        "def project_manifest(",
        "def project_read_file(",
        "def project_write_file(",
        "def project_php_lint(",
        "def project_deploy(",
        "def hostgator_health(",
    ):
        assert_marker(ROOT / "main.py", marker)

    print("MCP_MAIN_CATALOG_FILESYSTEM_GATE=PASS", flush=True)
    print("DOCKER_REBUILD_PERFORMED=NAO", flush=True)
    print(f"ROLLBACK_SOURCE={BACKUP_ROOT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
