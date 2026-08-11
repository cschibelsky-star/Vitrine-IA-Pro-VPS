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


def ensure_after(text: str, marker: str, addition: str, sentinel: str, label: str) -> str:
    if sentinel in text:
        return text
    count=text.count(marker)
    if count != 1:
        raise RuntimeError(f'{label}: esperado 1 marcador, encontrado {count}')
    return text.replace(marker, marker + addition, 1)


def ensure_before(text: str, marker: str, addition: str, sentinel: str, label: str) -> str:
    if sentinel in text:
        return text
    count=text.count(marker)
    if count != 1:
        raise RuntimeError(f'{label}: esperado 1 marcador, encontrado {count}')
    return text.replace(marker, addition + marker, 1)


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f'Raiz do conector não encontrada: {ROOT}')

    # Módulos versionados: helpers puros, registry e runtime.
    shutil.copy2(SOURCE / 'tvsumare_operations.py', ROOT / 'tvsumare_operations.py')
    shutil.copy2(SOURCE / 'main_tvsumare_tools.py', ROOT / 'tvsumare_tools.py')
    shutil.copy2(SOURCE / 'project_registry.py', ROOT / 'project_registry.py')
    shutil.copy2(SOURCE / 'connector_runtime.py', ROOT / 'connector_runtime.py')

    ops_broker = ROOT / 'ops_broker.py'
    backup(ops_broker)
    text = ops_broker.read_text(encoding='utf-8')
    text = ensure_after(
        text,
        'from via_operations import router as via_operations_router\n',
        'from tvsumare_operations import router as tvsumare_operations_router\n',
        'from tvsumare_operations import router as tvsumare_operations_router',
        'import do router TV Sumaré',
    )
    text = ensure_after(
        text,
        'app.include_router(via_operations_router)\n',
        'app.include_router(tvsumare_operations_router)\n',
        'app.include_router(tvsumare_operations_router)',
        'registro do router TV Sumaré',
    )
    ops_broker.write_text(text, encoding='utf-8')

    main_py = ROOT / 'main.py'
    backup(main_py)
    text = main_py.read_text(encoding='utf-8')
    import_marker = 'from typing import Any\n'
    imports = '''\nfrom connector_runtime import connector_health as _connector_health, project_context as _project_context\nfrom tvsumare_tools import (\n    tvsumare_health as _tvsumare_health,\n    tvsumare_workspace_create as _tvsumare_workspace_create,\n    tvsumare_write_file as _tvsumare_write_file,\n    tvsumare_git_status as _tvsumare_git_status,\n    tvsumare_php_lint as _tvsumare_php_lint,\n    tvsumare_docker_build as _tvsumare_docker_build,\n    tvsumare_docker_up as _tvsumare_docker_up,\n    tvsumare_create_homologation_vhost as _tvsumare_create_homologation_vhost,\n    tvsumare_create_release_zip as _tvsumare_create_release_zip,\n)\n'''
    text = ensure_after(text, import_marker, imports, 'from connector_runtime import connector_health as _connector_health', 'imports estabilizados')

    block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef connector_health() -> dict[str, Any]:\n    return _connector_health()\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_context(project_id: str) -> dict[str, Any]:\n    return _project_context(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef tvsumare_health() -> dict[str, Any]:\n    return _tvsumare_health()\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_workspace_create() -> dict[str, Any]:\n    return _tvsumare_workspace_create()\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_write_file(path: str, content: str, backup: bool = True) -> dict[str, Any]:\n    return _tvsumare_write_file(path, content, backup)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef tvsumare_git_status() -> dict[str, Any]:\n    return _tvsumare_git_status()\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef tvsumare_php_lint() -> dict[str, Any]:\n    return _tvsumare_php_lint()\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_docker_build() -> dict[str, Any]:\n    return _tvsumare_docker_build()\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_docker_up() -> dict[str, Any]:\n    return _tvsumare_docker_up()\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_create_homologation_vhost(domain: str = "tv-hml.vitrineiapro.com.br", upstream: str = "tvsumare_web:80") -> dict[str, Any]:\n    return _tvsumare_create_homologation_vhost(domain, upstream)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_create_release_zip() -> dict[str, Any]:\n    return _tvsumare_create_release_zip()\n'''
    marker = '\nif __name__ == "__main__":\n'
    text = ensure_before(text, marker, block, 'def connector_health() -> dict[str, Any]:', 'registro MCP estabilizado')
    main_py.write_text(text, encoding='utf-8')

    compose = ROOT / 'docker-compose.mcp.yml'
    backup(compose)
    compose_text = compose.read_text(encoding='utf-8')
    env_marker = '      OPS_TIMEOUT: 1200\n'
    env = (
        '      TVSUMARE_ROOT: /srv/tvsumare\n'
        '      TVSUMARE_BACKUP_ROOT: /srv/backups/tvsumare\n'
        '      NGINX_CONF_ROOT: /srv/vitrine/docker/nginx/conf.d\n'
        '      NGINX_HTML_ROOT: /srv/vitrine/docker/nginx/html\n'
        '      TVSUMARE_OPS_TIMEOUT: 1200\n'
    )
    compose_text = ensure_after(compose_text, env_marker, env, '      TVSUMARE_ROOT: /srv/tvsumare', 'variáveis ops_broker')
    volume_marker = '      - /var/run/docker.sock:/var/run/docker.sock\n'
    volumes = (
        '      - /srv/tvsumare:/srv/tvsumare:rw\n'
        '      - /srv/backups/tvsumare:/srv/backups/tvsumare:rw\n'
        '      - /srv/vitrine/docker/nginx/conf.d:/srv/vitrine/docker/nginx/conf.d:rw\n'
        '      - /srv/vitrine/docker/nginx/html:/srv/vitrine/docker/nginx/html:rw\n'
        '      - /srv/vitrine/ssl:/srv/vitrine/ssl:rw\n'
    )
    compose_text = ensure_after(compose_text, volume_marker, volumes, '      - /srv/tvsumare:/srv/tvsumare:rw', 'volumes ops_broker')
    compose.write_text(compose_text, encoding='utf-8')

    print('CONNECTOR_STABILIZATION_INSTALLED=SIM')
    print('CONNECTOR_ID=vitrine_ops')
    print('CONNECTOR_VERSION=2.1.0-stabilization.1')
    print(f'BACKUP_STAMP={STAMP}')


if __name__ == '__main__':
    main()
