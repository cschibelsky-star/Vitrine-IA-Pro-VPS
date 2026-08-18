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


def ensure_block_before(text: str, marker: str, block: str, sentinel: str, label: str) -> str:
    if sentinel in text:
        return text
    if marker not in text:
        raise RuntimeError(f'{label}: marcador não encontrado')
    return text.replace(marker, block + marker, 1)


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

    ops_broker = ROOT / 'ops_broker.py'
    backup(ops_broker)
    text = ops_broker.read_text(encoding='utf-8')
    text = ensure_line_after(
        text,
        'from tvsumare_migration_operations import router as tvsumare_migration_router\n',
        'from project_manager_operations import router as project_manager_router\n',
        'import project manager router',
    )
    text = ensure_line_after(
        text,
        'app.include_router(tvsumare_migration_router)\n',
        'app.include_router(project_manager_router)\n',
        'include project manager router',
    )
    ops_broker.write_text(text, encoding='utf-8')

    main_py = ROOT / 'main.py'
    backup(main_py)
    text = main_py.read_text(encoding='utf-8')

    import_block = '''\nfrom project_manager_tools import (\n    project_manifest as _project_manifest,\n    project_workspace as _project_workspace,\n    project_clone as _project_clone,\n    project_status as _project_status,\n    project_docker_container_info as _project_docker_container_info,\n    project_docker_container_env_safe as _project_docker_container_env_safe,\n)\n'''

    if 'from project_manager_tools import' not in text:
        marker = 'from tvsumare_migration_tools import ('
        index = text.find(marker)
        if index == -1:
            raise RuntimeError('imports project manager: marcador não encontrado')
        end = text.find(')\n', index)
        if end == -1:
            raise RuntimeError('imports project manager: fechamento não encontrado')
        end += 2
        text = text[:end] + import_block + text[end:]
    else:
        if 'project_docker_container_info as _project_docker_container_info' not in text:
            text = text.replace(
                '    project_status as _project_status,\n',
                '    project_status as _project_status,\n'
                '    project_docker_container_info as _project_docker_container_info,\n'
                '    project_docker_container_env_safe as _project_docker_container_env_safe,\n',
                1,
            )

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_manifest(project_id: str) -> dict[str, Any]:\n    return _project_manifest(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_workspace(project_id: str) -> dict[str, Any]:\n    return _project_workspace(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_clone(project_id: str) -> dict[str, Any]:\n    return _project_clone(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_status(project_id: str) -> dict[str, Any]:\n    return _project_status(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_docker_container_info(project_id: str, container_name: str) -> dict[str, Any]:\n    return _project_docker_container_info(project_id, container_name)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_docker_container_env_safe(project_id: str, container_name: str) -> dict[str, Any]:\n    return _project_docker_container_env_safe(project_id, container_name)\n'''

    text = ensure_block_before(
        text,
        '\nif __name__ == "__main__":\n',
        tools_block,
        'def project_clone(project_id:',
        'registro project manager tools',
    )
    if 'def project_docker_container_info(project_id:' not in text:
        marker = '\nif __name__ == "__main__":\n'
        extra = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_docker_container_info(project_id: str, container_name: str) -> dict[str, Any]:\n    return _project_docker_container_info(project_id, container_name)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_docker_container_env_safe(project_id: str, container_name: str) -> dict[str, Any]:\n    return _project_docker_container_env_safe(project_id, container_name)\n'''
        text = text.replace(marker, extra + marker, 1)
    main_py.write_text(text, encoding='utf-8')

    dockerfile = ROOT / 'Dockerfile'
    backup(dockerfile)
    docker_text = dockerfile.read_text(encoding='utf-8')
    copy_line = next(
        (line for line in docker_text.splitlines() if line.startswith('COPY ') and line.endswith(' ./')),
        None,
    )
    if not copy_line:
        raise RuntimeError('Dockerfile: linha COPY não encontrada')

    required = ['project_manager_operations.py', 'project_manager_tools.py']
    updated_line = copy_line
    for item in required:
        if item not in updated_line.split():
            updated_line = updated_line[:-3] + f' {item} ./'
    docker_text = docker_text.replace(copy_line, updated_line, 1)

    manifest_copy = 'COPY project-manifests ./project-manifests\n'
    if manifest_copy not in docker_text:
        docker_text = docker_text.replace(updated_line + '\n', updated_line + '\n' + manifest_copy, 1)

    dockerfile.write_text(docker_text, encoding='utf-8')

    compose_override = ROOT / 'docker-compose.connector-v2.override.yml'
    compose_template = SOURCE.parent / 'connector-v2' / 'docker-compose.connector-v2.override.yml'
    if not compose_override.exists():
        if not compose_template.exists():
            raise RuntimeError(f'Compose override ausente: {compose_override} e template não encontrado: {compose_template}')
        shutil.copy2(compose_template, compose_override)

    backup(compose_override)
    compose_text = compose_override.read_text(encoding='utf-8')

    compose_text = ensure_compose_entry(
        compose_text,
        'ops_broker',
        'environment',
        'PROJECT_MANIFEST_ROOT: /app/project-manifests',
    )
    compose_text = ensure_compose_entry(
        compose_text,
        'ops_broker',
        'environment',
        'PROJECT_WORKSPACE_ROOTS: /srv/tvsumare,/srv/projects',
    )
    compose_text = ensure_compose_entry(
        compose_text,
        'ops_broker',
        'environment',
        'PROJECT_DOCKER_ALLOWED_PREFIXES: vitrine_core_,cursos_ia_mvp_,tvsumare_,agente_compras_',
    )
    compose_text = ensure_compose_entry(
        compose_text,
        'ops_broker',
        'environment',
        'OPS_AUDIT_LOG: /var/log/vitrine-ops/audit.jsonl',
    )
    compose_text = ensure_compose_entry(
        compose_text,
        'ops_broker',
        'volumes',
        '- /srv/projects:/srv/projects:rw',
    )
    compose_text = ensure_compose_entry(
        compose_text,
        'ops_broker',
        'volumes',
        '- /var/log/vitrine-ops:/var/log/vitrine-ops:rw',
    )
    compose_text = ensure_compose_entry(
        compose_text,
        'vps_mcp_connector',
        'volumes',
        '- /srv/projects:/host/projects:ro',
    )

    compose_override.write_text(compose_text, encoding='utf-8')

    print('PROJECT_MANAGER_INSTALLED')
    print('PROJECT_DOCKER_DIAGNOSTICS_INSTALLED')
    print(f'BACKUP_STAMP={STAMP}')


if __name__ == '__main__':
    main()
