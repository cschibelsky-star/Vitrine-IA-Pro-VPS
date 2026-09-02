from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(os.getenv('CONNECTOR_ROOT', '/srv/connectors/vitrine-vps-mcp'))
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
    services_match = re.search(r'^services:\s*(?:#.*)?$', text, re.MULTILINE)
    if services_match is None:
        raise RuntimeError('Compose: bloco services não encontrado')

    next_top_level = re.search(
        r'^[A-Za-z0-9_.-]+:\s*(?:#.*)?$',
        text[services_match.end():],
        re.MULTILINE,
    )
    services_end = (
        len(text)
        if next_top_level is None
        else services_match.end() + next_top_level.start()
    )
    services_block = text[services_match.end():services_end]

    service_pattern = re.compile(
        rf'^  {re.escape(service)}:\s*(?:#.*)?$',
        re.MULTILINE,
    )
    service_match = service_pattern.search(services_block)
    if service_match is None:
        raise RuntimeError(f'Compose: serviço {service} não encontrado')

    service_start = services_match.end() + service_match.start()
    service_header_end = services_match.end() + service_match.end()
    next_service = re.search(
        r'^  [A-Za-z0-9_.-]+:\s*(?:#.*)?$',
        services_block[service_match.end():],
        re.MULTILINE,
    )
    service_end = (
        services_end
        if next_service is None
        else service_header_end + next_service.start()
    )
    service_block = text[service_start:service_end]

    section_pattern = re.compile(
        rf'^    {re.escape(section)}:\s*(?:#.*)?$',
        re.MULTILINE,
    )
    section_match = section_pattern.search(service_block)
    if section_match is None:
        insertion_at = service_header_end
        return text[:insertion_at] + f'\n    {section}:\n      {entry}' + text[insertion_at:]

    next_section = re.search(
        r'^    [A-Za-z0-9_.-]+:\s*(?:#.*)?$',
        service_block[section_match.end():],
        re.MULTILINE,
    )
    section_end = (
        len(service_block)
        if next_section is None
        else section_match.end() + next_section.start()
    )
    section_block = service_block[section_match.start():section_end]
    entry_pattern = re.compile(rf'^      {re.escape(entry)}\s*$', re.MULTILINE)
    if entry_pattern.search(section_block):
        return text

    insertion_at = service_start + section_match.end()
    return text[:insertion_at] + f'\n      {entry}' + text[insertion_at:]


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f'Raiz do conector não encontrada: {ROOT}')

    manifest_source = SOURCE / 'manifests'
    manifest_target = ROOT / 'project-manifests'
    manifest_target.mkdir(parents=True, exist_ok=True)

    shutil.copy2(SOURCE / 'project_manager_operations.py', ROOT / 'project_manager_operations.py')
    shutil.copy2(SOURCE / 'project_file_operations.py', ROOT / 'project_file_operations.py')
    shutil.copy2(SOURCE / 'project_manager_tools.py', ROOT / 'project_manager_tools.py')
    shutil.copy2(SOURCE / 'project_deployment_engine.py', ROOT / 'project_deployment_engine.py')

    for manifest in manifest_source.glob('*.json'):
        shutil.copy2(manifest, manifest_target / manifest.name)

    kernel_file = ROOT / 'factory_kernel.py'
    backup(kernel_file)
    kernel_text = kernel_file.read_text(encoding='utf-8')
    if 'def factory_kernel_decide_impl(capability: str)' not in kernel_text:
        old_kernel_signature = '@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef factory_kernel_decide(capability: str) -> dict[str, Any]:\n'
        if old_kernel_signature not in kernel_text:
            raise RuntimeError('Factory Kernel decide: assinatura original não encontrada')
        kernel_text = kernel_text.replace(
            old_kernel_signature,
            'def factory_kernel_decide_impl(capability: str) -> dict[str, Any]:\n',
            1,
        )
        kernel_text = kernel_text.rstrip() + '\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef factory_kernel_decide(capability: str) -> dict[str, Any]:\n    """Decide se uma capacidade deve ser reaproveitada, evoluída ou construída, sem executar alterações."""\n    return factory_kernel_decide_impl(capability)\n'
        kernel_file.write_text(kernel_text, encoding='utf-8')

    ops_broker = ROOT / 'ops_broker.py'
    backup(ops_broker)
    text = ops_broker.read_text(encoding='utf-8')
    text = text.replace(
        'from factory_kernel import factory_kernel_decide\n',
        'from factory_kernel import factory_kernel_decide_impl\n',
    )
    text = text.replace(
        'return factory_kernel_decide(value)',
        'return factory_kernel_decide_impl(value)',
    )

    factory_allowlist_anchor = '    "commercial:factory-intake",\n'
    for factory_command in ('factory:architect-request', 'factory:ai-plan', 'factory:intake-probe', 'factory:decision', 'factory:discovery-gate-probe'):
        factory_command_line = f'    "{factory_command}",\n'
        if factory_command_line not in text:
            if factory_allowlist_anchor not in text:
                raise RuntimeError('Factory allowlist: marcador commercial:factory-intake não encontrado')
            text = text.replace(
                factory_allowlist_anchor,
                factory_command_line + factory_allowlist_anchor,
                1,
            )

    factory_exec_old = '    result = run(["docker", "exec", LARAVEL_CONTAINER, "php", "artisan", req.command, *req.arguments], Path("/"))\n'
    factory_exec_probe = '    target_container = "vitrine_factory_hml_app" if req.command == "factory:intake-probe" else LARAVEL_CONTAINER\n    result = run(["docker", "exec", target_container, "php", "artisan", req.command, *req.arguments], Path("/"))\n'
    factory_exec_decision = '    target_container = "vitrine_factory_hml_app" if req.command in {"factory:intake-probe", "factory:decision"} else LARAVEL_CONTAINER\n    result = run(["docker", "exec", target_container, "php", "artisan", req.command, *req.arguments], Path("/"))\n'
    factory_exec_current = '    target_container = "vitrine_factory_hml_app" if req.command in {"factory:intake-probe", "factory:decision", "factory:discovery-gate-probe"} else LARAVEL_CONTAINER\n    result = run(["docker", "exec", target_container, "php", "artisan", req.command, *req.arguments], Path("/"))\n'
    if factory_exec_current not in text:
        if factory_exec_decision in text:
            text = text.replace(factory_exec_decision, factory_exec_current, 1)
        elif factory_exec_probe in text:
            text = text.replace(factory_exec_probe, factory_exec_current, 1)
        elif factory_exec_old in text:
            text = text.replace(factory_exec_old, factory_exec_current, 1)
        else:
            raise RuntimeError('Factory intake probe routing: marcador de execução não encontrado')

    text = ensure_line_after(
        text,
        'from tvsumare_migration_operations import router as tvsumare_migration_router\n',
        'from project_manager_operations import router as project_manager_router\n',
        'import project manager router',
    )
    text = ensure_line_after(
        text,
        'from project_manager_operations import router as project_manager_router\n',
        'from project_deployment_engine import router as project_deployment_router\n',
        'import project deployment router',
    )
    text = ensure_line_after(
        text,
        'from hostgator_broker_patch import build_router as build_hostgator_router\n',
        'from factory_kernel import factory_kernel_decide_impl\n',
        'import factory kernel decide impl',
    )
    text = ensure_line_after(
        text,
        'app.include_router(tvsumare_migration_router)\n',
        'app.include_router(project_manager_router)\n',
        'include project manager router',
    )
    text = ensure_line_after(
        text,
        'app.include_router(project_manager_router)\n',
        'app.include_router(project_deployment_router)\n',
        'include project deployment router',
    )
    kernel_endpoint = '''\n\n@app.get("/internal/factory-kernel/decide")\ndef internal_factory_kernel_decide(capability: str) -> dict[str, Any]:\n    value = " ".join(str(capability or "").split())[:500]\n    if len(value) < 3:\n        raise HTTPException(status_code=422, detail="capability_required")\n    return factory_kernel_decide_impl(value)\n\n\n@app.get("/internal/n8n/catalog")\ndef internal_n8n_catalog() -> dict[str, Any]:\n    try:\n        catalog = json.loads(N8N_CATALOG_RAW)\n    except json.JSONDecodeError:\n        catalog = {}\n    if not isinstance(catalog, dict):\n        catalog = {}\n    return {\"ok\": True, \"aliases\": sorted(str(key) for key in catalog.keys()), \"count\": len(catalog)}\n'''
    text = ensure_block_before(
        text,
        '\n@app.post("/artisan", dependencies=[Depends(auth)])\n',
        kernel_endpoint,
        'def internal_factory_kernel_decide(',
        'factory kernel internal endpoint',
    )
    text = text.replace(
        'target_container = "vitrine_factory_hml_app" if req.command == "factory:intake-probe" else LARAVEL_CONTAINER',
        'target_container = "vitrine_factory_hml_app" if req.command in {"factory:intake-probe", "factory:decision"} else LARAVEL_CONTAINER',
    )
    ops_broker.write_text(text, encoding='utf-8')

    compose_base = ROOT / 'docker-compose.mcp.yml'
    backup(compose_base)
    compose_base_text = compose_base.read_text(encoding='utf-8')
    compose_base_text = ensure_compose_entry(
        compose_base_text,
        'ops_broker',
        'networks',
        '- vitrine_net',
    )
    compose_base.write_text(compose_base_text, encoding='utf-8')

    main_py = ROOT / 'main.py'
    backup(main_py)
    text = main_py.read_text(encoding='utf-8')

    import_block = '''\nfrom project_manager_tools import (\n    project_manifest as _project_manifest,\n    project_workspace as _project_workspace,\n    project_clone as _project_clone,\n    project_status as _project_status,\n    project_docker_container_info as _project_docker_container_info,\n    project_docker_container_env_safe as _project_docker_container_env_safe,\n    project_compose_rm_explicit as _project_compose_rm_explicit,\n    project_git_stage_explicit as _project_git_stage_explicit,\n    project_git_commit_explicit as _project_git_commit_explicit,\n    project_write_file as _project_write_file,\n    project_php_lint as _project_php_lint,\n    project_deploy as _project_deploy,\n)\n'''

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
        import_start = text.find('from project_manager_tools import (')
        import_end = text.find(')\n', import_start)
        if import_end == -1:
            raise RuntimeError('imports project manager: fechamento não encontrado')
        import_lines = (
            '    project_docker_container_info as _project_docker_container_info,\n',
            '    project_docker_container_env_safe as _project_docker_container_env_safe,\n',
            '    project_compose_rm_explicit as _project_compose_rm_explicit,\n',
            '    project_git_stage_explicit as _project_git_stage_explicit,\n',
            '    project_git_commit_explicit as _project_git_commit_explicit,\n',
            '    project_write_file as _project_write_file,\n',
            '    project_php_lint as _project_php_lint,\n',
            '    project_deploy as _project_deploy,\n',
        )
        for import_line in import_lines:
            import_block_text = text[import_start:import_end]
            if import_line.strip() not in import_block_text:
                text = text[:import_end] + import_line + text[import_end:]
                import_end += len(import_line)

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_manifest(project_id: str) -> dict[str, Any]:\n    return _project_manifest(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_workspace(project_id: str) -> dict[str, Any]:\n    return _project_workspace(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_clone(project_id: str) -> dict[str, Any]:\n    return _project_clone(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_status(project_id: str) -> dict[str, Any]:\n    return _project_status(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_deploy(\n    project_id: str,\n    environment: str = "homologation",\n    update_repository: bool = True,\n    build: bool = True,\n    start: bool = True,\n) -> dict[str, Any]:\n    return _project_deploy(project_id, environment, update_repository, build, start)\n'''

    text = ensure_block_before(
        text,
        '\nif __name__ == "__main__":\n',
        tools_block,
        'def project_clone(project_id:',
        'registro project manager tools',
    )
    if 'def project_deploy(' not in text:
        project_deploy_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_deploy(\n    project_id: str,\n    environment: str = "homologation",\n    update_repository: bool = True,\n    build: bool = True,\n    start: bool = True,\n) -> dict[str, Any]:\n    return _project_deploy(project_id, environment, update_repository, build, start)\n'''
        text = ensure_block_before(
            text,
            '\nif __name__ == "__main__":\n',
            project_deploy_block,
            'def project_deploy(',
            'registro project deploy tool',
        )
    if 'def project_git_stage_explicit(' not in text:
        project_git_stage_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_git_stage_explicit(\n    project_id: str,\n    paths: list[str],\n    confirm: str = "",\n) -> dict[str, Any]:\n    return _project_git_stage_explicit(project_id, paths, confirm)\n'''
        text = ensure_block_before(
            text,
            '\nif __name__ == "__main__":\n',
            project_git_stage_block,
            'def project_git_stage_explicit(',
            'registro project git stage explicit tool',
        )
    if 'def project_git_commit_explicit(' not in text:
        project_git_commit_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_git_commit_explicit(\n    project_id: str,\n    message: str,\n    confirm: str = "",\n) -> dict[str, Any]:\n    return _project_git_commit_explicit(project_id, message, confirm)\n'''
        text = ensure_block_before(
            text,
            '\nif __name__ == "__main__":\n',
            project_git_commit_block,
            'def project_git_commit_explicit(',
            'registro project git commit explicit tool',
        )
    if 'def project_write_file(' not in text:
        project_write_file_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_write_file(\n    project_id: str,\n    path: str,\n    content: str,\n    backup: bool = True,\n    confirm: str = "",\n) -> dict[str, Any]:\n    return _project_write_file(project_id, path, content, backup, confirm)\n'''
        text = ensure_block_before(
            text,
            '\nif __name__ == "__main__":\n',
            project_write_file_block,
            'def project_write_file(',
            'registro project write file tool',
        )
    if 'def project_php_lint(' not in text:
        project_php_lint_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_php_lint(project_id: str, path: str) -> dict[str, Any]:\n    return _project_php_lint(project_id, path)\n'''
        text = ensure_block_before(
            text,
            '\nif __name__ == "__main__":\n',
            project_php_lint_block,
            'def project_php_lint(',
            'registro project php lint tool',
        )
    if 'def project_docker_container_info(' not in text:
        docker_info_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_docker_container_info(project_id: str, container_name: str) -> dict[str, Any]:\n    return _project_docker_container_info(project_id, container_name)\n'''
        text = ensure_block_before(
            text,
            '\nif __name__ == "__main__":\n',
            docker_info_block,
            'def project_docker_container_info(',
            'registro project docker container info tool',
        )
    if 'def project_docker_container_env_safe(' not in text:
        docker_env_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_docker_container_env_safe(project_id: str, container_name: str) -> dict[str, Any]:\n    return _project_docker_container_env_safe(project_id, container_name)\n'''
        text = ensure_block_before(
            text,
            '\nif __name__ == "__main__":\n',
            docker_env_block,
            'def project_docker_container_env_safe(',
            'registro project docker container env safe tool',
        )
    if 'def project_compose_rm_explicit(' not in text:
        compose_rm_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})\ndef project_compose_rm_explicit(\n    project_id: str,\n    compose_file: str,\n    services: list[str],\n    docker_project: str = "",\n    confirm: str = "",\n) -> dict[str, Any]:\n    return _project_compose_rm_explicit(project_id, compose_file, services, docker_project, confirm)\n'''
        text = ensure_block_before(
            text,
            '\nif __name__ == "__main__":\n',
            compose_rm_block,
            'def project_compose_rm_explicit(',
            'registro project compose rm explicit tool',
        )
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

    required = [
        'project_manager_operations.py',
        'project_file_operations.py',
        'project_manager_tools.py',
        'project_deployment_engine.py',
    ]
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
    compose_text = re.sub(
        r'^\s{6}PROJECT_DOCKER_ALLOWED_PREFIXES:.*\n?',
        '',
        compose_text,
        flags=re.MULTILINE,
    )

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
        'PROJECT_DOCKER_ALLOWED_PREFIXES: vitrine_core_,cursos_ia_mvp_,tvsumare_,agente_compras_,vitrine_factory_,studio_,vitrine_social_',
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
    print(f'BACKUP_STAMP={STAMP}')


if __name__ == '__main__':
    main()
