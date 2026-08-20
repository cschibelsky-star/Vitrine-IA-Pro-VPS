from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.backup-project-manager-{STAMP}'))


def ensure_line_after(text: str, anchor: str, line: str, label: str) -> str:
    if line in text:
        return text
    if anchor not in text:
        raise RuntimeError(f'{label}: marcador não encontrado')
    return text.replace(anchor, anchor + line, 1)


def ensure_compose_entry(text: str, service: str, section: str, entry: str) -> str:
    service_marker = f'  {service}:\n'
    if service_marker not in text:
        raise RuntimeError(f'Compose: serviço {service} não encontrado')
    service_start = text.index(service_marker)
    next_service = text.find('\n  ', service_start + len(service_marker))
    service_end = len(text) if next_service == -1 else next_service
    service_block = text[service_start:service_end]
    if entry in service_block:
        return text
    section_marker = f'    {section}:\n'
    section_pos = service_block.find(section_marker)
    if section_pos == -1:
        insertion = service_marker + f'    {section}:\n      {entry}\n'
        return text.replace(service_marker, insertion, 1)
    absolute_section = service_start + section_pos + len(section_marker)
    return text[:absolute_section] + f'      {entry}\n' + text[absolute_section:]


def replace_project_manager_imports(text: str) -> str:
    start = text.find('from project_manager_tools import (')
    block = '''from project_manager_tools import (\n    project_manifest as _project_manifest,\n    project_workspace as _project_workspace,\n    project_clone as _project_clone,\n    project_status as _project_status,\n    project_docker_container_info as _project_docker_container_info,\n    project_docker_container_env_safe as _project_docker_container_env_safe,\n    project_container_exec as _project_container_exec,\n    project_http_check as _project_http_check,\n    project_port_check as _project_port_check,\n    project_compose_explicit as _project_compose_explicit,\n    project_file_read_safe as _project_file_read_safe,\n    project_file_patch_text as _project_file_patch_text,\n    project_manifest_repository_update as _project_manifest_repository_update,\n)\n'''
    if start == -1:
        marker = 'from tvsumare_migration_tools import ('
        index = text.find(marker)
        if index == -1:
            raise RuntimeError('imports project manager: marcador não encontrado')
        end = text.find(')\n', index)
        if end == -1:
            raise RuntimeError('imports project manager: fechamento não encontrado')
        return text[:end + 2] + '\n' + block + text[end + 2:]
    end = text.find(')\n', start)
    if end == -1:
        raise RuntimeError('imports project manager: fechamento não encontrado')
    return text[:start] + block + text[end + 2:]


def replace_project_manager_tools(text: str) -> str:
    marker = '\nif __name__ == "__main__":\n'
    if marker not in text:
        raise RuntimeError('registro MCP: marcador __main__ não encontrado')
    first = text.find('@mcp.tool', text.find('def project_manifest(') - 120 if 'def project_manifest(' in text else 0)
    if first != -1 and first < text.find(marker):
        prefix = text[:first]
    else:
        prefix = text[:text.find(marker)]
    tools = '''\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_manifest(project_id: str) -> dict[str, Any]: return _project_manifest(project_id)\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_workspace(project_id: str) -> dict[str, Any]: return _project_workspace(project_id)\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_clone(project_id: str) -> dict[str, Any]: return _project_clone(project_id)\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_status(project_id: str) -> dict[str, Any]: return _project_status(project_id)\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_docker_container_info(project_id: str, container_name: str) -> dict[str, Any]: return _project_docker_container_info(project_id, container_name)\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_docker_container_env_safe(project_id: str, container_name: str) -> dict[str, Any]: return _project_docker_container_env_safe(project_id, container_name)\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_container_exec(project_id: str, container_name: str, command: list[str], workdir: str = "/var/www/html", confirm: str = "") -> dict[str, Any]: return _project_container_exec(project_id, container_name, command, workdir, confirm)\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_http_check(project_id: str, url: str, method: str = "GET") -> dict[str, Any]: return _project_http_check(project_id, url, method)\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_port_check(project_id: str, host: str, port: int) -> dict[str, Any]: return _project_port_check(project_id, host, port)\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_compose_explicit(project_id: str, compose_file: str, action: str = "status", docker_project: str = "", confirm: str = "") -> dict[str, Any]: return _project_compose_explicit(project_id, compose_file, action, docker_project, confirm)\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_file_read_safe(project_id: str, path: str, max_bytes: int = 100000) -> dict[str, Any]: return _project_file_read_safe(project_id, path, max_bytes)\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_file_patch_text(project_id: str, path: str, old: str, new: str, confirm: str = "") -> dict[str, Any]: return _project_file_patch_text(project_id, path, old, new, confirm)\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_manifest_repository_update(project_id: str, url: str, branch: str, confirm: str = "") -> dict[str, Any]: return _project_manifest_repository_update(project_id, url, branch, confirm)\n'''
    return prefix.rstrip() + '\n\n' + tools + marker + text.split(marker, 1)[1]


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f'Raiz do conector não encontrada: {ROOT}')
    manifest_source = SOURCE / 'manifests'
    manifest_target = ROOT / 'project-manifests'
    manifest_target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE / 'project_manager_operations.py', ROOT / 'project_manager_operations.py')
    shutil.copy2(SOURCE / 'project_manager_tools.py', ROOT / 'project_manager_tools.py')
    for manifest in manifest_source.glob('*.json'):
        shutil.copy2(manifest, manifest_target / manifest.name)

    ops_broker = ROOT / 'ops_broker.py'; backup(ops_broker); text = ops_broker.read_text(encoding='utf-8')
    text = ensure_line_after(text, 'from tvsumare_migration_operations import router as tvsumare_migration_router\n',
                             'from project_manager_operations import router as project_manager_router\n', 'import project manager router')
    text = ensure_line_after(text, 'app.include_router(tvsumare_migration_router)\n',
                             'app.include_router(project_manager_router)\n', 'include project manager router')
    ops_broker.write_text(text, encoding='utf-8')

    main_py = ROOT / 'main.py'; backup(main_py); text = main_py.read_text(encoding='utf-8')
    text = replace_project_manager_imports(text)
    text = replace_project_manager_tools(text)
    main_py.write_text(text, encoding='utf-8')

    dockerfile = ROOT / 'Dockerfile'; backup(dockerfile); docker_text = dockerfile.read_text(encoding='utf-8')
    copy_line = next((line for line in docker_text.splitlines() if line.startswith('COPY ') and line.endswith(' ./')), None)
    if not copy_line: raise RuntimeError('Dockerfile: linha COPY não encontrada')
    updated_line = copy_line
    for item in ['project_manager_operations.py', 'project_manager_tools.py']:
        if item not in updated_line.split(): updated_line = updated_line[:-3] + f' {item} ./'
    docker_text = docker_text.replace(copy_line, updated_line, 1)
    if 'COPY project-manifests ./project-manifests\n' not in docker_text:
        docker_text = docker_text.replace(updated_line + '\n', updated_line + '\nCOPY project-manifests ./project-manifests\n', 1)
    dockerfile.write_text(docker_text, encoding='utf-8')

    compose_override = ROOT / 'docker-compose.connector-v2.override.yml'
    compose_template = SOURCE.parent / 'connector-v2' / 'docker-compose.connector-v2.override.yml'
    if not compose_override.exists():
        if not compose_template.exists(): raise RuntimeError('Compose override ausente e template não encontrado')
        shutil.copy2(compose_template, compose_override)
    backup(compose_override); compose_text = compose_override.read_text(encoding='utf-8')
    entries = [
        ('ops_broker', 'environment', 'PROJECT_MANIFEST_ROOT: /app/project-manifests'),
        ('ops_broker', 'environment', 'PROJECT_WORKSPACE_ROOTS: /srv/tvsumare,/srv/projects'),
        ('ops_broker', 'environment', 'PROJECT_DOCKER_ALLOWED_PREFIXES: vitrine_core_,cursos_ia_mvp_,tvsumare_,agente_compras_,via_'),
        ('ops_broker', 'environment', 'OPS_AUDIT_LOG: /var/log/vitrine-ops/audit.jsonl'),
        ('ops_broker', 'volumes', '- /srv/projects:/srv/projects:rw'),
        ('ops_broker', 'volumes', '- /var/log/vitrine-ops:/var/log/vitrine-ops:rw'),
        ('vps_mcp_connector', 'volumes', '- /srv/projects:/host/projects:ro'),
    ]
    for service, section, entry in entries: compose_text = ensure_compose_entry(compose_text, service, section, entry)
    compose_override.write_text(compose_text, encoding='utf-8')
    print('PROJECT_MANAGER_V2_INSTALLED'); print('PROJECT_SAFE_OPS_INSTALLED'); print(f'BACKUP_STAMP={STAMP}')


if __name__ == '__main__':
    main()
