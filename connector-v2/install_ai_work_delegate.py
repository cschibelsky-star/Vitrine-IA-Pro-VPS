from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp"))
# Host directory of the budget ledger. It MUST stay outside ROOT: the release updater
# backs up ROOT and, on failure, renames it and restores the backup. A ledger inside ROOT
# would be rolled back (resetting the R$10 cap) and would not survive a rebuild.
LEDGER_HOST_DIR = Path(os.getenv("AI_WORK_DELEGATE_HOST_DIR", "/srv/data/vitrine-ai-work-delegate"))
LEDGER_CONTAINER_DIR = "/data/ai-work-delegate"
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
MODULES = (
    "ai_work_delegate.py",
    "roteia_delegate_adapter.py",
    "roteia_transport.py",
    "ai_work_delegate_tool.py",
    "acceptance_ai_work_delegate.py",
)
OVERRIDE_NAME = "docker-compose.connector-v2.override.yml"
SERVICE = "vps_mcp_connector"
ENV_ENTRIES = (
    f"AI_WORK_DELEGATE_LEDGER: {LEDGER_CONTAINER_DIR}/ledger.sqlite",
    "ROTEIA_API_KEY: ${ROTEIA_API_KEY:-}",
    "ROTEIA_MODEL_ID: ${ROTEIA_MODEL_ID:-}",
    "ROTEIA_PRICE_INPUT_CENTS_PER_MTOK: ${ROTEIA_PRICE_INPUT_CENTS_PER_MTOK:-}",
    "ROTEIA_PRICE_OUTPUT_CENTS_PER_MTOK: ${ROTEIA_PRICE_OUTPUT_CENTS_PER_MTOK:-}",
    "ROTEIA_MAX_OUTPUT_TOKENS: ${ROTEIA_MAX_OUTPUT_TOKENS:-}",
)

IMPORT_BLOCK = (
    "\nfrom ai_work_delegate_tool import (\n"
    "    ai_work_delegate_status as _ai_work_delegate_status,\n"
    "    ai_work_delegate_tool as _ai_work_delegate_tool,\n"
    ")\n"
)
TOOLS_BLOCK = '''

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def ai_work_delegate(experiment_id: str, prompt: str, max_charge_cents: int = 100, confirm: str = "") -> dict[str, Any]:
    """Delega uma tarefa limitada ao Claude via Roteia (somente HML). Uma chamada por experiment_id, teto total de R$ 10, exige confirm=EXECUTAR."""
    return _ai_work_delegate_tool(experiment_id, prompt, max_charge_cents, confirm)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def ai_work_delegate_status() -> dict[str, Any]:
    """Estado do ledger de custos e da configuração da Roteia, sem segredos."""
    return _ai_work_delegate_status()
'''


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.backup-ai-work-delegate-{STAMP}"))


def ensure_after(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marcador nao encontrado para {identity}: {marker!r}")
    return text.replace(marker, marker + addition, 1)


def ensure_before(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f"marcador nao encontrado para {identity}: {marker!r}")
    return text.replace(marker, addition + marker, 1)


def ensure_compose_entry(text: str, service: str, section: str, entry: str) -> str:
    services_match = re.search(r"^services:\s*(?:#.*)?$", text, re.MULTILINE)
    if services_match is None:
        raise RuntimeError("Compose: bloco services nao encontrado")

    next_top_level = re.search(r"^[A-Za-z0-9_.-]+:\s*(?:#.*)?$", text[services_match.end():], re.MULTILINE)
    services_end = len(text) if next_top_level is None else services_match.end() + next_top_level.start()
    services_block = text[services_match.end():services_end]

    service_match = re.search(rf"^  {re.escape(service)}:\s*(?:#.*)?$", services_block, re.MULTILINE)
    if service_match is None:
        raise RuntimeError(f"Compose: servico {service} nao encontrado")

    service_start = services_match.end() + service_match.start()
    service_header_end = services_match.end() + service_match.end()
    next_service = re.search(r"^  [A-Za-z0-9_.-]+:\s*(?:#.*)?$", services_block[service_match.end():], re.MULTILINE)
    service_end = services_end if next_service is None else service_header_end + next_service.start()
    service_block = text[service_start:service_end]

    section_match = re.search(rf"^    {re.escape(section)}:\s*(?:#.*)?$", service_block, re.MULTILINE)
    if section_match is None:
        return text[:service_header_end] + f"\n    {section}:\n      {entry}" + text[service_header_end:]

    next_section = re.search(r"^    [A-Za-z0-9_.-]+:\s*(?:#.*)?$", service_block[section_match.end():], re.MULTILINE)
    section_end = len(service_block) if next_section is None else section_match.end() + next_section.start()
    section_block = service_block[section_match.start():section_end]
    if re.search(rf"^      {re.escape(entry)}\s*$", section_block, re.MULTILINE):
        return text

    insertion_at = service_start + section_match.end()
    return text[:insertion_at] + f"\n      {entry}" + text[insertion_at:]


def inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f"Raiz do conector nao encontrada: {ROOT}")
    if inside(LEDGER_HOST_DIR, ROOT):
        raise SystemExit("ledger_host_dir_inside_connector_root: o ledger seria revertido por backup/rollback")

    for name in MODULES:
        shutil.copy2(SOURCE / name, ROOT / name)

    main_py = ROOT / "main.py"
    backup(main_py)
    text = main_py.read_text(encoding="utf-8")
    text = ensure_after(text, "from typing import Any\n", IMPORT_BLOCK, "from ai_work_delegate_tool import (")
    text = ensure_before(text, '\nif __name__ == "__main__":\n', TOOLS_BLOCK, "def ai_work_delegate(")
    main_py.write_text(text, encoding="utf-8")

    dockerfile = ROOT / "Dockerfile"
    backup(dockerfile)
    docker_text = dockerfile.read_text(encoding="utf-8")
    copy_line = next(
        (line for line in docker_text.splitlines() if line.startswith("COPY ") and line.endswith(" ./")),
        None,
    )
    if not copy_line:
        raise RuntimeError("Dockerfile: linha COPY nao encontrada")
    updated_line = copy_line
    for name in MODULES:
        if name not in updated_line.split():
            updated_line = updated_line[:-3] + f" {name} ./"
    docker_text = docker_text.replace(copy_line, updated_line, 1)
    dockerfile.write_text(docker_text, encoding="utf-8")

    override = ROOT / OVERRIDE_NAME
    if not override.is_file():
        raise RuntimeError(f"{OVERRIDE_NAME} nao encontrado em {ROOT}; rode install_project_manager antes")
    backup(override)
    compose_text = override.read_text(encoding="utf-8")
    for entry in ENV_ENTRIES:
        compose_text = ensure_compose_entry(compose_text, SERVICE, "environment", entry)
    compose_text = ensure_compose_entry(
        compose_text, SERVICE, "volumes", f"- {LEDGER_HOST_DIR}:{LEDGER_CONTAINER_DIR}:rw"
    )
    override.write_text(compose_text, encoding="utf-8")

    try:
        LEDGER_HOST_DIR.mkdir(parents=True, exist_ok=True)
        print(f"LEDGER_HOST_DIR_READY={LEDGER_HOST_DIR}")
    except OSError:
        print(f"LEDGER_HOST_DIR_PRECREATE=SKIPPED ({LEDGER_HOST_DIR}); o docker cria o bind mount")

    print("AI_WORK_DELEGATE_INSTALLED=SIM")
    print(f"BACKUP_STAMP={STAMP}")


if __name__ == "__main__":
    main()
