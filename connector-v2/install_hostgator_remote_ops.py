from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp"))
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.backup-hostgator-v4-{STAMP}"))


def ensure_line_after(text: str, anchor: str, line: str, label: str) -> str:
    if line in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"{label}: marcador nao encontrado")
    return text.replace(anchor, anchor + line, 1)


def ensure_block_before(text: str, marker: str, block: str, sentinel: str, label: str) -> str:
    if sentinel in text:
        return text
    if marker not in text:
        raise RuntimeError(f"{label}: marcador nao encontrado")
    return text.replace(marker, block + marker, 1)


def restore_last_healthy_project_manager_main(main_py: Path) -> str:
    backups = sorted(
        ROOT.glob("main.py.backup-project-manager-*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not backups:
        raise RuntimeError("backup project-manager do main.py nao encontrado")

    selected = backups[0]
    safety = ROOT / f"main.py.before-recovery-{STAMP}"
    if main_py.exists():
        shutil.copy2(main_py, safety)
    shutil.copy2(selected, main_py)
    return selected.name


def preserve_mcp_main_in_next_installer() -> None:
    installer = SOURCE.parent / "project-manager" / "install_project_manager.py"
    if not installer.is_file():
        raise RuntimeError("install_project_manager.py nao encontrado")

    text = installer.read_text(encoding="utf-8")
    start_marker = '    main_py = ROOT / "main.py"\n'
    end_marker = '    dockerfile = ROOT / "Dockerfile"\n'

    start = text.find(start_marker)
    end = text.find(end_marker, start if start >= 0 else 0)
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("bloco de mutacao do main.py nao localizado")

    replacement = (
        '    # Recovery mode: preserve the existing MCP main.py registry.\n'
        '    # Project modules and broker routes are still updated below.\n'
        '    main_py = ROOT / "main.py"\n'
        '    if not main_py.exists():\n'
        '        raise RuntimeError("main.py runtime ausente")\n\n'
    )
    installer.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f"Raiz do conector nao encontrada: {ROOT}")

    for name in ("hostgator_operations.py", "hostgator_tools.py"):
        source = SOURCE / name
        if not source.exists():
            raise SystemExit(f"Arquivo fonte ausente: {source}")
        shutil.copy2(source, ROOT / name)

    ops_broker = ROOT / "ops_broker.py"
    main_py = ROOT / "main.py"
    dockerfile = ROOT / "Dockerfile"
    for required in (ops_broker, main_py, dockerfile):
        if not required.exists():
            raise SystemExit(f"Arquivo runtime ausente: {required}")

    restored_from = restore_last_healthy_project_manager_main(main_py)

    backup(ops_broker)
    text = ops_broker.read_text(encoding="utf-8")
    import_anchor = "from project_manager_operations import router as project_manager_router\n"
    include_anchor = "app.include_router(project_manager_router)\n"
    text = ensure_line_after(text, import_anchor, "from hostgator_operations import router as hostgator_router\n", "import hostgator router")
    text = ensure_line_after(text, include_anchor, "app.include_router(hostgator_router)\n", "include hostgator router")
    ops_broker.write_text(text, encoding="utf-8")

    backup(main_py)
    text = main_py.read_text(encoding="utf-8")
    import_block = '''\nfrom hostgator_tools import (\n    hostgator_health as _hostgator_health,\n    hostgator_git_status as _hostgator_git_status,\n    hostgator_git_compare as _hostgator_git_compare,\n    hostgator_read_file as _hostgator_read_file,\n)\n'''
    if "from hostgator_tools import" not in text:
        marker = "from project_manager_tools import ("
        index = text.find(marker)
        if index == -1:
            raise RuntimeError("imports hostgator tools: project_manager_tools nao encontrado")
        end = text.find(")\n", index)
        if end == -1:
            raise RuntimeError("imports hostgator tools: fechamento nao encontrado")
        end += 2
        text = text[:end] + import_block + text[end:]

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_health() -> dict[str, Any]:\n    return _hostgator_health()\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_git_status(root: str) -> dict[str, Any]:\n    return _hostgator_git_status(root)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_git_compare(root: str) -> dict[str, Any]:\n    return _hostgator_git_compare(root)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_read_file(root: str, path: str, max_bytes: int = 100000) -> dict[str, Any]:\n    return _hostgator_read_file(root, path, max_bytes)\n'''
    text = ensure_block_before(text, '\nif __name__ == "__main__":\n', tools_block, "def hostgator_health()", "registro tools hostgator")
    main_py.write_text(text, encoding="utf-8")

    backup(dockerfile)
    docker_text = dockerfile.read_text(encoding="utf-8")
    if "openssh-client" not in docker_text:
        if "apt-get install -y --no-install-recommends" not in docker_text:
            raise RuntimeError("Dockerfile: bloco apt-get nao encontrado")
        docker_text = docker_text.replace("apt-get install -y --no-install-recommends", "apt-get install -y --no-install-recommends openssh-client", 1)

    copy_line = next((line for line in docker_text.splitlines() if line.startswith("COPY ") and line.endswith(" ./")), None)
    if not copy_line:
        raise RuntimeError("Dockerfile: linha COPY de modulos nao encontrada")
    updated_line = copy_line
    for name in ("hostgator_operations.py", "hostgator_tools.py"):
        if name not in updated_line.split():
            updated_line = updated_line[:-3] + f" {name} ./"
    docker_text = docker_text.replace(copy_line, updated_line, 1)
    dockerfile.write_text(docker_text, encoding="utf-8")

    preserve_mcp_main_in_next_installer()

    print("HOSTGATOR_REMOTE_OPS_V4_PREPARED")
    print(f"MCP_MAIN_RECOVERED_FROM={restored_from}")
    print("PROJECT_MANAGER_MAIN_PRESERVE=SIM")
    print(f"BACKUP_STAMP={STAMP}")
    print("REQUIRED_ENV=HOSTGATOR_SSH_HOST,HOSTGATOR_SSH_USER,HOSTGATOR_SSH_PORT,HOSTGATOR_SSH_KEY_FILE")


if __name__ == "__main__":
    main()
