from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp-main")).resolve()

RUNTIME_FILES = (
    "server.py",
    "main.py",
    "ops_broker.py",
    "via_operations.py",
    "via_tools.py",
    "hostgator_operations.py",
    "hostgator_tools.py",
    "tvsumare_operations.py",
    "tvsumare_tools.py",
    "connector_runtime.py",
    "connector_observability.py",
    "probe_streamable_http.py",
    "project_manager_operations.py",
    "project_file_operations.py",
    "project_manager_tools.py",
    "project_deployment_engine.py",
    "project_read_operations.py",
    "project_shared_operations.py",
    "project_explicit_operations.py",
)


def require(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"required packaging input missing: {path}")


def main() -> int:
    require(ROOT)
    dockerfile = ROOT / "Dockerfile"
    require(dockerfile)
    require(ROOT / "requirements.txt")
    require(ROOT / "project-manifests")
    for name in RUNTIME_FILES:
        require(ROOT / name)

    text = dockerfile.read_text(encoding="utf-8")
    lines = text.splitlines()

    copy_index = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("COPY ") and "server.py" in stripped and "main.py" in stripped and "ops_broker.py" in stripped:
            copy_index = index
            break
    if copy_index is None:
        raise RuntimeError("Dockerfile canonical runtime COPY anchor not found")

    canonical_copy = "COPY " + " ".join(RUNTIME_FILES) + " ./"
    lines[copy_index] = canonical_copy

    manifest_line = "COPY project-manifests ./project-manifests"
    lines = [line for line in lines if line.strip() != manifest_line]
    copy_index = lines.index(canonical_copy)
    lines.insert(copy_index + 1, manifest_line)

    dockerfile.write_text("\n".join(lines) + "\n", encoding="utf-8")

    final = dockerfile.read_text(encoding="utf-8")
    for name in RUNTIME_FILES:
        if name not in final:
            raise RuntimeError(f"Dockerfile packaging gate missing: {name}")
    if manifest_line not in final:
        raise RuntimeError("Dockerfile packaging gate missing project-manifests")

    print("MCP_CANONICAL_PACKAGING=PASS")
    print(f"RUNTIME_FILE_COUNT={len(RUNTIME_FILES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
