from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv("CONNECTOR_ROOT", "/srv/connectors/vitrine-vps-mcp"))
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.backup-project-manager-{STAMP}"))


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


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f"Raiz do conector nao encontrada: {ROOT}")

    manifest_source = SOURCE / "manifests"
    manifest_target = ROOT / "project-manifests"
    manifest_target.mkdir(parents=True, exist_ok=True)

    modules = (
        "project_manager_operations.py",
        "project_file_operations.py",
        "project_manager_tools.py",
        "project_deployment_engine.py",
        "project_read_operations.py",
        "project_shared_operations.py",
        "project_explicit_operations.py",
    )
    for item in modules:
        source = SOURCE / item
        if not source.is_file():
            raise RuntimeError(f"modulo obrigatorio ausente: {item}")
        shutil.copy2(source, ROOT / item)

    for manifest in manifest_source.glob("*.json"):
        shutil.copy2(manifest, manifest_target / manifest.name)

    ops_broker = ROOT / "ops_broker.py"
    backup(ops_broker)
    text = ops_broker.read_text(encoding="utf-8")
    import_anchor = "from tvsumare_operations import router as tvsumare_operations_router\n"
    imports = (
        ("from project_manager_operations import router as project_manager_router\n", "project_manager_router"),
        ("from project_read_operations import router as project_read_router\n", "project_read_router"),
        ("from project_shared_operations import router as project_shared_router\n", "project_shared_router"),
        ("from project_explicit_operations import router as project_explicit_router\n", "project_explicit_router"),
        ("from project_deployment_engine import router as project_deployment_router\n", "project_deployment_router"),
    )
    for line, identity in imports:
        text = ensure_after(text, import_anchor, line, identity)
        import_anchor = line

    include_anchor = "app.include_router(tvsumare_operations_router)\n"
    includes = (
        ("app.include_router(project_manager_router)\n", "include_router(project_manager_router)"),
        ("app.include_router(project_read_router)\n", "include_router(project_read_router)"),
        ("app.include_router(project_shared_router)\n", "include_router(project_shared_router)"),
        ("app.include_router(project_explicit_router)\n", "include_router(project_explicit_router)"),
        ("app.include_router(project_deployment_router)\n", "include_router(project_deployment_router)"),
    )
    for line, identity in includes:
        text = ensure_after(text, include_anchor, line, identity)
        include_anchor = line
    ops_broker.write_text(text, encoding="utf-8")

    main_py = ROOT / "main.py"
    backup(main_py)
    text = main_py.read_text(encoding="utf-8")
    import_marker = "from typing import Any\n"
    import_block = '''\nfrom project_manager_tools import (\n    project_manifest as _project_manifest,\n    project_workspace as _project_workspace,\n    project_clone as _project_clone,\n    project_status as _project_status,\n    project_git_status as _project_git_status,\n    project_file_read_safe as _project_file_read_safe,\n    project_read_file as _project_read_file,\n    project_file_patch_text as _project_file_patch_text,\n    project_compose_explicit as _project_compose_explicit,\n    project_git_stage_explicit as _project_git_stage_explicit,\n    project_git_commit_explicit as _project_git_commit_explicit,\n    project_write_file as _project_write_file,\n    project_php_lint as _project_php_lint,\n    project_deploy as _project_deploy,\n)\n'''
    if "from project_manager_tools import (" in text:
        start = text.index("from project_manager_tools import (")
        end = text.index(")\n", start) + 2
        text = text[:start] + import_block.lstrip("\n") + text[end:]
    else:
        text = ensure_after(text, import_marker, import_block, "from project_manager_tools import (")

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_manifest(project_id: str) -> dict[str, Any]:\n    return _project_manifest(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_workspace(project_id: str) -> dict[str, Any]:\n    return _project_workspace(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_clone(project_id: str) -> dict[str, Any]:\n    return _project_clone(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_status(project_id: str) -> dict[str, Any]:\n    return _project_status(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_git_status(project_id: str) -> dict[str, Any]:\n    return _project_git_status(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_file_read_safe(project_id: str, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:\n    return _project_file_read_safe(project_id, path, start_line, end_line)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_read_file(project_id: str, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:\n    return _project_read_file(project_id, path, start_line, end_line)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_file_patch_text(project_id: str, path: str, old: str, new: str, confirm: str = "") -> dict[str, Any]:\n    return _project_file_patch_text(project_id, path, old, new, confirm)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_compose_explicit(project_id: str, compose_file: str, action: str = "status", docker_project: str = "", confirm: str = "") -> dict[str, Any]:\n    return _project_compose_explicit(project_id, compose_file, action, docker_project, confirm)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_git_stage_explicit(project_id: str, paths: list[str], confirm: str = "") -> dict[str, Any]:\n    return _project_git_stage_explicit(project_id, paths, confirm)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_git_commit_explicit(project_id: str, message: str, confirm: str = "") -> dict[str, Any]:\n    return _project_git_commit_explicit(project_id, message, confirm)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_write_file(project_id: str, path: str, content: str, backup: bool = True, confirm: str = "") -> dict[str, Any]:\n    return _project_write_file(project_id, path, content, backup, confirm)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_php_lint(project_id: str, path: str) -> dict[str, Any]:\n    return _project_php_lint(project_id, path)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_deploy(project_id: str, environment: str = "homologation", update_repository: bool = True, build: bool = True, start: bool = True) -> dict[str, Any]:\n    return _project_deploy(project_id, environment, update_repository, build, start)\n'''
    marker = '\nif __name__ == "__main__":\n'
    function_names = (
        "project_manifest", "project_workspace", "project_clone", "project_status", "project_git_status",
        "project_file_read_safe", "project_read_file", "project_file_patch_text", "project_compose_explicit",
        "project_git_stage_explicit", "project_git_commit_explicit", "project_write_file", "project_php_lint", "project_deploy",
    )
    for name in function_names:
        pattern = re.compile(rf"\n@mcp\.tool\([^\n]*\)\ndef {name}\(.*?(?=\n@mcp\.tool|\nif __name__ == \"__main__\":)", re.DOTALL)
        text = pattern.sub("", text)
    text = ensure_before(text, marker, tools_block, "def project_file_read_safe(")
    main_py.write_text(text, encoding="utf-8")

    dockerfile = ROOT / "Dockerfile"
    backup(dockerfile)
    docker_text = dockerfile.read_text(encoding="utf-8")
    copy_line = next((line for line in docker_text.splitlines() if line.startswith("COPY ") and line.endswith(" ./")), None)
    if not copy_line:
        raise RuntimeError("Dockerfile: linha COPY nao encontrada")
    updated_line = copy_line
    for item in modules:
        if item not in updated_line.split():
            updated_line = updated_line[:-3] + f" {item} ./"
    docker_text = docker_text.replace(copy_line, updated_line, 1)
    manifest_copy = "COPY project-manifests ./project-manifests\n"
    if manifest_copy not in docker_text:
        docker_text = docker_text.replace(updated_line + "\n", updated_line + "\n" + manifest_copy, 1)
    dockerfile.write_text(docker_text, encoding="utf-8")

    compose_override = ROOT / "docker-compose.connector-v2.override.yml"
    compose_template = SOURCE.parent / "connector-v2" / "docker-compose.connector-v2.override.yml"
    if not compose_override.exists():
        shutil.copy2(compose_template, compose_override)
    backup(compose_override)
    compose_text = compose_override.read_text(encoding="utf-8")
    for section, entry in (
        ("environment", "PROJECT_MANIFEST_ROOT: /app/project-manifests"),
        ("environment", "PROJECT_WORKSPACE_ROOTS: /srv/tvsumare,/srv/projects"),
        ("environment", "OPS_AUDIT_LOG: /var/log/vitrine-ops/audit.jsonl"),
        ("volumes", "- /srv/projects:/srv/projects:rw"),
        ("volumes", "- /var/log/vitrine-ops:/var/log/vitrine-ops:rw"),
    ):
        compose_text = ensure_compose_entry(compose_text, "ops_broker", section, entry)
    compose_text = ensure_compose_entry(compose_text, "vps_mcp_connector", "volumes", "- /srv/projects:/host/projects:ro")
    compose_override.write_text(compose_text, encoding="utf-8")

    print("PROJECT_MANAGER_INSTALLED_V4_COMPLETE")
    print(f"BACKUP_STAMP={STAMP}")


if __name__ == "__main__":
    main()
