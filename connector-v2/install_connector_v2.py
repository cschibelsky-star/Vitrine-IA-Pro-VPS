from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.backup-tvsumare-v2-{STAMP}'))


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: esperado 1 ocorrência, encontrado {count}')
    return text.replace(old, new, 1)


def ensure_line_after(text: str, marker: str, line: str, label: str) -> str:
    if line in text:
        return text
    return replace_once(text, marker, marker + line, label)


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f'Raiz do conector não encontrada: {ROOT}')

    shutil.copy2(SOURCE / 'tvsumare_operations.py', ROOT / 'tvsumare_operations.py')
    shutil.copy2(SOURCE / 'main_tvsumare_tools.py', ROOT / 'tvsumare_tools.py')

    ops_broker = ROOT / 'ops_broker.py'
    backup(ops_broker)
    text = ops_broker.read_text(encoding='utf-8')
    if 'from tvsumare_operations import router as tvsumare_operations_router\n' not in text:
        text = replace_once(
            text,
            'from via_operations import router as via_operations_router\n',
            'from via_operations import router as via_operations_router\n'
            'from tvsumare_operations import router as tvsumare_operations_router\n',
            'import do router TV Sumaré',
        )
    if 'app.include_router(tvsumare_operations_router)\n' not in text:
        text = replace_once(
            text,
            'app.include_router(via_operations_router)\n',
            'app.include_router(via_operations_router)\n'
            'app.include_router(tvsumare_operations_router)\n',
            'registro do router TV Sumaré',
        )
    ops_broker.write_text(text, encoding='utf-8')

    main_py = ROOT / 'main.py'
    backup(main_py)
    text = main_py.read_text(encoding='utf-8')
    import_marker = 'from typing import Any\n'
    if 'from tvsumare_tools import' not in text:
        text = replace_once(
            text,
            import_marker,
            import_marker + '\nfrom tvsumare_tools import (\n'
            '    tvsumare_health as _tvsumare_health,\n'
            '    tvsumare_workspace_create as _tvsumare_workspace_create,\n'
            '    tvsumare_write_file as _tvsumare_write_file,\n'
            '    tvsumare_git_status as _tvsumare_git_status,\n'
            '    tvsumare_php_lint as _tvsumare_php_lint,\n'
            '    tvsumare_docker_build as _tvsumare_docker_build,\n'
            '    tvsumare_docker_up as _tvsumare_docker_up,\n'
            '    tvsumare_issue_homologation_certificate as _tvsumare_issue_homologation_certificate,\n'
            '    tvsumare_create_homologation_vhost as _tvsumare_create_homologation_vhost,\n'
            '    tvsumare_publish_homologation as _tvsumare_publish_homologation,\n'
            '    tvsumare_create_release_zip as _tvsumare_create_release_zip,\n'
            ')\n',
            'imports de ferramentas TV Sumaré',
        )

    block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def tvsumare_health() -> dict[str, Any]:
    return _tvsumare_health()


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_workspace_create() -> dict[str, Any]:
    return _tvsumare_workspace_create()


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_write_file(path: str, content: str, backup: bool = True) -> dict[str, Any]:
    return _tvsumare_write_file(path, content, backup)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def tvsumare_git_status() -> dict[str, Any]:
    return _tvsumare_git_status()


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def tvsumare_php_lint() -> dict[str, Any]:
    return _tvsumare_php_lint()


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_docker_build() -> dict[str, Any]:
    return _tvsumare_docker_build()


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_docker_up() -> dict[str, Any]:
    return _tvsumare_docker_up()


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_issue_homologation_certificate(
    domain: str = "tv-hml.vitrineiapro.com.br",
    email: str = "cschibelsky@gmail.com",
) -> dict[str, Any]:
    return _tvsumare_issue_homologation_certificate(domain, email)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_create_homologation_vhost(
    domain: str = "tv-hml.vitrineiapro.com.br",
    upstream: str = "tvsumare_web:80",
) -> dict[str, Any]:
    return _tvsumare_create_homologation_vhost(domain, upstream)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_publish_homologation(
    domain: str = "tv-hml.vitrineiapro.com.br",
    upstream: str = "tvsumare_web:80",
    email: str = "cschibelsky@gmail.com",
) -> dict[str, Any]:
    return _tvsumare_publish_homologation(domain, upstream, email)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def tvsumare_create_release_zip() -> dict[str, Any]:
    return _tvsumare_create_release_zip()
'''
    marker = '\nif __name__ == "__main__":\n'
    if 'def tvsumare_workspace_create()' not in text:
        text = replace_once(text, marker, block + marker, 'registro MCP TV Sumaré')
    elif 'def tvsumare_publish_homologation(' not in text:
        text = replace_once(text, marker, block + marker, 'atualização MCP TV Sumaré')
    main_py.write_text(text, encoding='utf-8')

    compose = ROOT / 'docker-compose.mcp.yml'
    backup(compose)
    compose_text = compose.read_text(encoding='utf-8')
    env_marker = '      OPS_TIMEOUT: 1200\n'
    if 'TVSUMARE_ROOT:' not in compose_text:
        compose_text = replace_once(
            compose_text,
            env_marker,
            env_marker
            + '      TVSUMARE_ROOT: /srv/tvsumare\n'
            + '      TVSUMARE_BACKUP_ROOT: /srv/backups/tvsumare\n'
            + '      NGINX_CONF_ROOT: /srv/vitrine/docker/nginx/conf.d\n'
            + '      NGINX_HTML_ROOT: /srv/vitrine/docker/nginx/html\n'
            + '      VITRINE_SSL_ROOT: /srv/vitrine/ssl\n'
            + '      CERTBOT_IMAGE: certbot/certbot:latest\n'
            + '      TVSUMARE_OPS_TIMEOUT: 1200\n',
            'variáveis ops_broker',
        )
    else:
        compose_text = ensure_line_after(
            compose_text,
            '      NGINX_HTML_ROOT: /srv/vitrine/docker/nginx/html\n',
            '      VITRINE_SSL_ROOT: /srv/vitrine/ssl\n',
            'VITRINE_SSL_ROOT',
        )
        compose_text = ensure_line_after(
            compose_text,
            '      VITRINE_SSL_ROOT: /srv/vitrine/ssl\n',
            '      CERTBOT_IMAGE: certbot/certbot:latest\n',
            'CERTBOT_IMAGE',
        )
    volume_marker = '      - /var/run/docker.sock:/var/run/docker.sock\n'
    if '/srv/tvsumare:/srv/tvsumare:rw' not in compose_text:
        compose_text = replace_once(
            compose_text,
            volume_marker,
            volume_marker
            + '      - /srv/tvsumare:/srv/tvsumare:rw\n'
            + '      - /srv/backups/tvsumare:/srv/backups/tvsumare:rw\n'
            + '      - /srv/vitrine/docker/nginx/conf.d:/srv/vitrine/docker/nginx/conf.d:rw\n'
            + '      - /srv/vitrine/docker/nginx/html:/srv/vitrine/docker/nginx/html:rw\n'
            + '      - /srv/vitrine/ssl:/srv/vitrine/ssl:rw\n',
            'volumes ops_broker',
        )
    compose.write_text(compose_text, encoding='utf-8')

    print('CONNECTOR_V2_TVSUMARE_INSTALADO')
    print(f'BACKUP_STAMP={STAMP}')


if __name__ == '__main__':
    main()
