from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp-main")).resolve()
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.backup-via-mcp-{STAMP}"))


def ensure_after(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marker missing for {identity}: {marker!r}")
    return text.replace(marker, marker + addition, 1)


def ensure_before(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marker missing for {identity}: {marker!r}")
    return text.replace(marker, addition + marker, 1)


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f"connector root not found: {ROOT}")

    shutil.copy2(SOURCE / "via_tools.py", ROOT / "via_tools.py")

    main_py = ROOT / "main.py"
    backup(main_py)
    text = main_py.read_text(encoding="utf-8")

    import_marker = "from typing import Any\n"
    import_block = '''from via_tools import (\n    via_health as _via_health,\n    via_list_files as _via_list_files,\n    via_read_file as _via_read_file,\n    via_write_file as _via_write_file,\n    via_execute_command as _via_execute_command,\n)\n'''
    text = ensure_after(text, import_marker, import_block, "from via_tools import (")

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef via_health() -> dict[str, Any]:\n    """Verifica se o workspace operacional da VIA está disponível."""\n    return _via_health()\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef via_list_files(path: str = ".", max_entries: int = 500) -> dict[str, Any]:\n    """Lista diretórios e arquivos dentro do workspace da VIA."""\n    return _via_list_files(path, max_entries)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef via_read_file(path: str, max_bytes: int = 100000) -> dict[str, Any]:\n    """Lê um arquivo textual dentro do workspace da VIA."""\n    return _via_read_file(path, max_bytes)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef via_write_file(path: str, content: str, confirm: str = "") -> dict[str, Any]:\n    """Grava um arquivo da VIA. Use confirm='EXECUTAR'."""\n    return _via_write_file(path, content, confirm)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef via_execute_command(command: list[str], cwd: str = ".", timeout: int = 300, confirm: str = "") -> dict[str, Any]:\n    """Executa comando autorizado dentro da VIA. Use confirm='EXECUTAR'."""\n    return _via_execute_command(command, cwd, timeout, confirm)\n'''

    marker = '\nif __name__ == "__main__":\n'
    text = ensure_before(text, marker, tools_block, "def via_execute_command(")
    main_py.write_text(text, encoding="utf-8")

    dockerfile = ROOT / "Dockerfile"
    backup(dockerfile)
    docker_text = dockerfile.read_text(encoding="utf-8")
    copy_line = next((line for line in docker_text.splitlines() if line.startswith("COPY ") and line.endswith(" ./")), None)
    if not copy_line:
        raise RuntimeError("Dockerfile COPY line not found")
    if "via_tools.py" not in copy_line.split():
        updated = copy_line[:-3] + " via_tools.py ./"
        docker_text = docker_text.replace(copy_line, updated, 1)
    dockerfile.write_text(docker_text, encoding="utf-8")

    print("VIA_MCP_TOOLS_INSTALLED=SIM")
    print(f"BACKUP_STAMP={STAMP}")


if __name__ == "__main__":
    main()
