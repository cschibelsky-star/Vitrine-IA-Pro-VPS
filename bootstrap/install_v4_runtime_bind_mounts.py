from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp")).resolve()
SOURCE = Path(__file__).resolve().parent
OVERRIDE = ROOT / "docker-compose.connector-v2.override.yml"
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")


def _service_bounds(text: str, service: str) -> tuple[int, int, int]:
    services_match = re.search(r"^services:\s*(?:#.*)?$", text, re.MULTILINE)
    if services_match is None:
        raise RuntimeError("compose_services_missing")
    next_top = re.search(r"^[A-Za-z0-9_.-]+:\s*(?:#.*)?$", text[services_match.end():], re.MULTILINE)
    services_end = len(text) if next_top is None else services_match.end() + next_top.start()
    services_block = text[services_match.end():services_end]
    service_match = re.search(rf"^  {re.escape(service)}:\s*(?:#.*)?$", services_block, re.MULTILINE)
    if service_match is None:
        raise RuntimeError(f"compose_service_missing:{service}")
    service_start = services_match.end() + service_match.start()
    service_header_end = services_match.end() + service_match.end()
    next_service = re.search(r"^  [A-Za-z0-9_.-]+:\s*(?:#.*)?$", services_block[service_match.end():], re.MULTILINE)
    service_end = services_end if next_service is None else service_header_end + next_service.start()
    return service_start, service_header_end, service_end


def ensure_compose_entry(text: str, service: str, section: str, entry: str) -> str:
    service_start, service_header_end, service_end = _service_bounds(text, service)
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


def set_service_command(text: str, service: str, command: str) -> str:
    service_start, service_header_end, service_end = _service_bounds(text, service)
    service_block = text[service_start:service_end]
    command_line = f"    command: {command}"
    pattern = re.compile(r"^    command:.*$", re.MULTILINE)
    if pattern.search(service_block):
        updated = pattern.sub(command_line, service_block, count=1)
        return text[:service_start] + updated + text[service_end:]
    return text[:service_header_end] + "\n" + command_line + text[service_header_end:]


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f"runtime_missing:{ROOT}")
    if not OVERRIDE.is_file():
        raise SystemExit(f"override_missing:{OVERRIDE}")

    entry_source = SOURCE / "v4_broker_entrypoint.py"
    entry_target = ROOT / "v4_broker_entrypoint.py"
    if not entry_source.is_file():
        raise SystemExit(f"entrypoint_source_missing:{entry_source}")
    shutil.copy2(entry_source, entry_target)

    required = [
        "ops_broker.py",
        "main.py",
        "v4_broker_entrypoint.py",
        "project_manager_operations.py",
        "project_file_operations.py",
        "project_manager_tools.py",
        "project_deployment_engine.py",
        "project_read_operations.py",
        "project_shared_operations.py",
        "project_explicit_operations.py",
    ]
    missing = [name for name in required if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit("runtime_modules_missing:" + ",".join(missing))

    backup = OVERRIDE.with_name(f"{OVERRIDE.name}.backup-bind-v4-{STAMP}")
    shutil.copy2(OVERRIDE, backup)
    text = OVERRIDE.read_text(encoding="utf-8")

    broker_mounts = [
        "- /srv/connectors/vitrine-vps-mcp/ops_broker.py:/app/ops_broker.py:ro",
        "- /srv/connectors/vitrine-vps-mcp/v4_broker_entrypoint.py:/app/v4_broker_entrypoint.py:ro",
        "- /srv/connectors/vitrine-vps-mcp/project_manager_operations.py:/app/project_manager_operations.py:ro",
        "- /srv/connectors/vitrine-vps-mcp/project_file_operations.py:/app/project_file_operations.py:ro",
        "- /srv/connectors/vitrine-vps-mcp/project_deployment_engine.py:/app/project_deployment_engine.py:ro",
        "- /srv/connectors/vitrine-vps-mcp/project_read_operations.py:/app/project_read_operations.py:ro",
        "- /srv/connectors/vitrine-vps-mcp/project_shared_operations.py:/app/project_shared_operations.py:ro",
        "- /srv/connectors/vitrine-vps-mcp/project_explicit_operations.py:/app/project_explicit_operations.py:ro",
        "- /srv/connectors/vitrine-vps-mcp/project-manifests:/app/project-manifests:ro",
    ]
    connector_mounts = [
        "- /srv/connectors/vitrine-vps-mcp/main.py:/app/main.py:ro",
        "- /srv/connectors/vitrine-vps-mcp/project_manager_tools.py:/app/project_manager_tools.py:ro",
    ]

    for entry in broker_mounts:
        text = ensure_compose_entry(text, "ops_broker", "volumes", entry)
    for entry in connector_mounts:
        text = ensure_compose_entry(text, "vps_mcp_connector", "volumes", entry)

    text = set_service_command(
        text,
        "ops_broker",
        '["uvicorn", "v4_broker_entrypoint:app", "--host", "0.0.0.0", "--port", "8770"]',
    )

    OVERRIDE.write_text(text, encoding="utf-8")
    print("V4_RUNTIME_BIND_MOUNTS_INSTALLED=PASS")
    print("V4_BROKER_ENTRYPOINT_ENABLED=PASS")
    print(f"BACKUP={backup}")


if __name__ == "__main__":
    main()
