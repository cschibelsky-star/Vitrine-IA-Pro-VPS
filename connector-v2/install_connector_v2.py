from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.backup-connector-stabilization-{STAMP}'))


def ensure_after(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f'marcador não encontrado para {identity}: {marker!r}')
    return text.replace(marker, marker + addition, 1)


def ensure_before(text: str, marker: str, addition: str, identity: str) -> str:
    if identity in text:
        return text
    if marker not in text:
        raise RuntimeError(f'marcador não encontrado para {identity}: {marker!r}')
    return text.replace(marker, addition + marker, 1)


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f'Raiz do conector não encontrada: {ROOT}')

    # Helpers não registram MCP; o registry é exclusivo do main.py.
    shutil.copy2(SOURCE / 'tvsumare_operations.py', ROOT / 'tvsumare_operations.py')
    shutil.copy2(SOURCE / 'main_tvsumare_tools.py', ROOT / 'tvsumare_tools.py')
    shutil.copy2(SOURCE / 'connector_runtime.py', ROOT / 'connector_runtime.py')

    ops_broker = ROOT / 'ops_broker.py'
    backup(ops_broker)
    text = ops_broker.read_text(encoding='utf-8')
    text = ensure_after(
        text,
        'from via_operations import router as via_operations_router\n',
        'from tvsumare_operations import router as tvsumare_operations_router\n',
        'from tvsumare_operations import router as tvsumare_operations_router',
    )
    text = ensure_after(
        text,
        'app.include_router(via_operations_router)\n',
        'app.include_router(tvsumare_operations_router)\n',
        'app.include_router(tvsumare_operations_router)',
    )
    ops_broker.write_text(text, encoding='utf-8')

    main_py = ROOT / 'main.py'
    backup(main_py)
    text = main_py.read_text(encoding='utf-8')
    import_marker = 'from typing import Any\n'

    tv_import = '''\nfrom tvsumare_tools import (\n    tvsumare_health as _tvsumare_health,\n    tvsumare_workspace_create as _tvsumare_workspace_create,\n    tvsumare_write_file as _tvsumare_write_file,\n    tvsumare_git_status as _tvsumare_git_status,\n    tvsumare_php_lint as _tvsumare_php_lint,\n    tvsumare_docker_build as _tvsumare_docker_build,\n    tvsumare_docker_up as _tvsumare_docker_up,\n    tvsumare_create_homologation_vhost as _tvsumare_create_homologation_vhost,\n    tvsumare_create_release_zip as _tvsumare_create_release_zip,\n)\n'''
    text = ensure_after(text, import_marker, tv_import, 'from tvsumare_tools import (')

    runtime_import = '''from connector_runtime import (\n    connector_health as _connector_health,\n    project_context as _project_context,\n)\n'''
    text = ensure_after(text, import_marker, runtime_import, 'from connector_runtime import (')

    tv_tools = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef tvsumare_health() -> dict[str, Any]:\n    return _tvsumare_health()\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_workspace_create() -> dict[str, Any]:\n    return _tvsumare_workspace_create()\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_write_file(path: str, content: str, backup: bool = True) -> dict[str, Any]:\n    return _tvsumare_write_file(path, content, backup)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef tvsumare_git_status() -> dict[str, Any]:\n    return _tvsumare_git_status()\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef tvsumare_php_lint() -> dict[str, Any]:\n    return _tvsumare_php_lint()\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_docker_build() -> dict[str, Any]:\n    return _tvsumare_docker_build()\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_docker_up() -> dict[str, Any]:\n    return _tvsumare_docker_up()\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_create_homologation_vhost(\n    domain: str = "tv-hml.vitrineiapro.com.br",\n    upstream: str = "tvsumare_web:80",\n) -> dict[str, Any]:\n    return _tvsumare_create_homologation_vhost(domain, upstream)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_create_release_zip() -> dict[str, Any]:\n    return _tvsumare_create_release_zip()\n'''
    marker = '\nif __name__ == "__main__":\n'
    text = ensure_before(text, marker, tv_tools, 'def tvsumare_workspace_create()')

    runtime_tools = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef connector_health() -> dict[str, Any]:\n    """Retorna versão, registry e projetos conhecidos do Centro Operacional."""\n    return _connector_health()\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_context(project_id: str) -> dict[str, Any]:\n    """Retorna o contexto canônico do projeto sem inferir caminhos."""\n    return _project_context(project_id)\n'''
    text = ensure_before(text, marker, runtime_tools, 'def connector_health()')
    main_py.write_text(text, encoding='utf-8')

    compose = ROOT / 'docker-compose.mcp.yml'
    backup(compose)
    compose_text = compose.read_text(encoding='utf-8')
    env_marker = '      OPS_TIMEOUT: 1200\n'
    env_add = (
        '      TVSUMARE_ROOT: /srv/tvsumare\n'
        '      TVSUMARE_BACKUP_ROOT: /srv/backups/tvsumare\n'
        '      NGINX_CONF_ROOT: /srv/vitrine/docker/nginx/conf.d\n'
        '      NGINX_HTML_ROOT: /srv/vitrine/docker/nginx/html\n'
        '      TVSUMARE_OPS_TIMEOUT: 1200\n'
    )
    if 'TVSUMARE_ROOT:' not in compose_text:
        compose_text = ensure_after(compose_text, env_marker, env_add, 'TVSUMARE_ROOT:')

    volume_marker = '      - /var/run/docker.sock:/var/run/docker.sock\n'
    volume_add = (
        '      - /srv/tvsumare:/srv/tvsumare:rw\n'
        '      - /srv/backups/tvsumare:/srv/backups/tvsumare:rw\n'
        '      - /srv/vitrine/docker/nginx/conf.d:/srv/vitrine/docker/nginx/conf.d:rw\n'
        '      - /srv/vitrine/docker/nginx/html:/srv/vitrine/docker/nginx/html:rw\n'
        '      - /srv/vitrine/ssl:/srv/vitrine/ssl:rw\n'
    )
    if '/srv/tvsumare:/srv/tvsumare:rw' not in compose_text:
        compose_text = ensure_after(compose_text, volume_marker, volume_add, '/srv/tvsumare:/srv/tvsumare:rw')
    compose.write_text(compose_text, encoding='utf-8')

    print('CONNECTOR_V2_STABILIZATION_INSTALLED=SIM')
    print(f'BACKUP_STAMP={STAMP}')


if __name__ == '__main__':
    main()
