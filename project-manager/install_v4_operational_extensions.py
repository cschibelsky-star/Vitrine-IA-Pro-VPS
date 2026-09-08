from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp")).resolve()
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")

REQUIRED_IMAGE_MODULES = (
    "tvsumare_operations.py",
    "tvsumare_tools.py",
    "hostgator_operations.py",
    "hostgator_tools.py",
    "connector_runtime.py",
    "connector_observability.py",
    "probe_streamable_http.py",
    "project_manager_operations.py",
    "project_manager_tools.py",
    "project_file_operations.py",
    "project_read_operations.py",
    "project_shared_operations.py",
    "project_explicit_operations.py",
    "project_deployment_engine.py",
    "container_diagnostics.py",
    "container_diagnostics_tools.py",
)


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.backup-v4-extensions-{STAMP}"))


def ensure_before(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marker_missing:{identity}")
    return text.replace(marker, addition + marker, 1)


def ensure_after(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marker_missing:{identity}")
    return text.replace(marker, marker + addition, 1)


def patch_dockerfile() -> None:
    dockerfile = ROOT / "Dockerfile"
    if not dockerfile.is_file():
        raise SystemExit("dockerfile_missing")
    backup(dockerfile)
    text = dockerfile.read_text(encoding="utf-8")

    has_docker_cli = "docker.io" in text or "docker-ce-cli" in text
    has_compose = "docker-compose" in text or "docker-compose-plugin" in text

    if has_docker_cli and not has_compose:
        marker = "apt-get install -y --no-install-recommends docker.io"
        if marker in text:
            text = text.replace(marker, marker + " docker-compose", 1)
        else:
            lines = text.splitlines()
            if not lines or not lines[0].startswith("FROM "):
                raise SystemExit("dockerfile_from_missing")
            install = (
                "\nRUN apt-get update \\\n"
                "    && apt-get install -y --no-install-recommends docker-compose \\\n"
                "    && rm -rf /var/lib/apt/lists/*\n"
            )
            text = lines[0] + install + "\n" + "\n".join(lines[1:]) + ("\n" if text.endswith("\n") else "")
    elif not has_docker_cli:
        lines = text.splitlines()
        if not lines or not lines[0].startswith("FROM "):
            raise SystemExit("dockerfile_from_missing")
        install = (
            "\nRUN apt-get update \\\n"
            "    && apt-get install -y --no-install-recommends docker.io docker-compose \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n"
        )
        text = lines[0] + install + "\n" + "\n".join(lines[1:]) + ("\n" if text.endswith("\n") else "")

    missing_runtime = [name for name in REQUIRED_IMAGE_MODULES if not (ROOT / name).is_file()]
    if missing_runtime:
        raise SystemExit("runtime_modules_missing:" + ",".join(missing_runtime))

    copy_line = next(
        (line for line in text.splitlines() if line.startswith("COPY ") and line.endswith(" ./")),
        None,
    )
    if not copy_line:
        raise SystemExit("dockerfile_copy_line_missing")

    updated_line = copy_line
    for name in REQUIRED_IMAGE_MODULES:
        if name not in updated_line.split():
            updated_line = updated_line[:-3] + f" {name} ./"
    text = text.replace(copy_line, updated_line, 1)

    final_tokens = set(updated_line.split())
    missing_copy = [name for name in REQUIRED_IMAGE_MODULES if name not in final_tokens]
    if missing_copy:
        raise SystemExit("dockerfile_modules_missing:" + ",".join(missing_copy))

    dockerfile.write_text(text, encoding="utf-8")


def install_manifest_and_tools() -> None:
    tools_source = SOURCE / "container_diagnostics_tools.py"
    tools_target = ROOT / "container_diagnostics_tools.py"
    manifest_source = SOURCE / "manifests" / "vitrine-vps-mcp-v59-integration.json"
    manifest_target = ROOT / "project-manifests" / "vitrine-vps-mcp-v59-integration.json"
    if not tools_source.is_file() or not manifest_source.is_file():
        raise SystemExit("extension_source_missing")
    ROOT.joinpath("project-manifests").mkdir(parents=True, exist_ok=True)
    backup(tools_target)
    backup(manifest_target)
    shutil.copy2(tools_source, tools_target)
    shutil.copy2(manifest_source, manifest_target)


def patch_main() -> None:
    main_py = ROOT / "main.py"
    if not main_py.is_file():
        raise SystemExit("main_missing")
    backup(main_py)
    text = main_py.read_text(encoding="utf-8")
    import_block = '''\nfrom container_diagnostics_tools import (\n    container_status as _container_status,\n    container_logs as _container_logs,\n)\n'''
    if "from container_diagnostics_tools import (" not in text:
        text = ensure_after(
            text,
            "from typing import Any\n",
            import_block,
            "from container_diagnostics_tools import (",
        )

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef container_status(name: str) -> dict[str, Any]:\n    return _container_status(name)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef container_logs(name: str, tail: int = 200) -> dict[str, Any]:\n    return _container_logs(name, tail)\n'''
    if "def container_status(" not in text:
        text = ensure_before(
            text,
            '\nif __name__ == "__main__":\n',
            tools_block,
            "def container_status(",
        )
    main_py.write_text(text, encoding="utf-8")


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f"runtime_missing:{ROOT}")
    install_manifest_and_tools()
    patch_main()
    patch_dockerfile()
    print("V4_OPERATIONAL_EXTENSIONS_INSTALLED=PASS")
    print("V4_IMAGE_PACKAGING_VALIDATED=PASS")
    print("V4_IMAGE_MODULE_COUNT=" + str(len(REQUIRED_IMAGE_MODULES)))
    print(f"BACKUP_STAMP={STAMP}")


if __name__ == "__main__":
    main()
