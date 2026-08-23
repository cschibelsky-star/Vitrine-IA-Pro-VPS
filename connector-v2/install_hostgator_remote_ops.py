from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.backup-hostgator-v4-port-{STAMP}'))


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


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f'Raiz do conector não encontrada: {ROOT}')

    required_sources = ['hostgator_operations.py', 'hostgator_tools.py']
    for source_name in required_sources:
        source = SOURCE / source_name
        target = ROOT / source_name
        if not source.exists():
            raise SystemExit(f'Arquivo fonte ausente: {source}')
        shutil.copy2(source, target)

    ops_broker = ROOT / 'ops_broker.py'
    if not ops_broker.exists():
        raise SystemExit(f'Broker não encontrado: {ops_broker}')
    backup(ops_broker)
    text = ops_broker.read_text(encoding='utf-8')
    text = ensure_line_after(
        text,
        'from tvsumare_migration_operations import router as tvsumare_migration_router\n',
        'from hostgator_operations import router as hostgator_router\n',
        'import hostgator router',
    )
    text = ensure_line_after(
        text,
        'app.include_router(tvsumare_migration_router)\n',
        'app.include_router(hostgator_router)\n',
        'include hostgator router',
    )
    ops_broker.write_text(text, encoding='utf-8')

    main_py = ROOT / 'main.py'
    if not main_py.exists():
        raise SystemExit(f'MCP main não encontrado: {main_py}')
    backup(main_py)
    text = main_py.read_text(encoding='utf-8')

    import_block = '''\nfrom hostgator_tools import (\n    hostgator_health as _hostgator_health,\n    hostgator_git_status as _hostgator_git_status,\n    hostgator_git_compare as _hostgator_git_compare,\n    hostgator_read_file as _hostgator_read_file,\n)\n'''
    if 'from hostgator_tools import' not in text:
        anchor = 'from tvsumare_migration_tools import ('
        index = text.find(anchor)
        if index == -1:
            raise RuntimeError('imports hostgator tools: marcador tvsumare_migration_tools não encontrado')
        end = text.find(')\n', index)
        if end == -1:
            raise RuntimeError('imports hostgator tools: fechamento não encontrado')
        end += 2
        text = text[:end] + import_block + text[end:]

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_health() -> dict[str, Any]:\n    return _hostgator_health()\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_git_status(root: str) -> dict[str, Any]:\n    return _hostgator_git_status(root)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_git_compare(root: str) -> dict[str, Any]:\n    return _hostgator_git_compare(root)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef hostgator_read_file(root: str, path: str, max_bytes: int = 100000) -> dict[str, Any]:\n    return _hostgator_read_file(root, path, max_bytes)\n'''
    text = ensure_block_before(
        text,
        '\nif __name__ == "__main__":\n',
        tools_block,
        'def hostgator_health()',
        'registro ferramentas hostgator',
    )
    main_py.write_text(text, encoding='utf-8')

    dockerfile = ROOT / 'Dockerfile'
    if not dockerfile.exists():
        raise SystemExit(f'Dockerfile não encontrado: {dockerfile}')
    backup(dockerfile)
    docker_text = dockerfile.read_text(encoding='utf-8')
    if 'openssh-client' not in docker_text:
        apt_anchor = 'apt-get install -y --no-install-recommends '
        idx = docker_text.find(apt_anchor)
        if idx == -1:
            raise RuntimeError('Dockerfile: bloco apt-get não encontrado')
        line_end = docker_text.find('\n', idx)
        line = docker_text[idx:line_end]
        docker_text = docker_text[:idx] + line + ' openssh-client' + docker_text[line_end:]

    copy_line = next(
        (line for line in docker_text.splitlines() if line.startswith('COPY ') and line.endswith(' ./')),
        None,
    )
    if not copy_line:
        raise RuntimeError('Dockerfile: linha COPY de módulos não encontrada')
    updated_line = copy_line
    for item in required_sources:
        if item not in updated_line.split():
            updated_line = updated_line[:-3] + f' {item} ./'
    docker_text = docker_text.replace(copy_line, updated_line, 1)
    dockerfile.write_text(docker_text, encoding='utf-8')

    compose = ROOT / 'docker-compose.mcp.yml'
    if compose.exists():
        backup(compose)
        compose_text = compose.read_text(encoding='utf-8')
        env_anchor = '      OPS_TIMEOUT: 1200\n'
        env_block = (
            '      HOSTGATOR_SSH_HOST: ${HOSTGATOR_SSH_HOST:-}\n'
            '      HOSTGATOR_SSH_USER: ${HOSTGATOR_SSH_USER:-}\n'
            '      HOSTGATOR_SSH_PORT: ${HOSTGATOR_SSH_PORT:-2222}\n'
            '      HOSTGATOR_SSH_KEY_FILE: /run/secrets/hostgator_ops_key\n'
            '      HOSTGATOR_HOME_ROOT: ${HOSTGATOR_HOME_ROOT:-/home1/cris1649}\n'
            '      HOSTGATOR_ALLOWED_ROOTS: ${HOSTGATOR_ALLOWED_ROOTS:-public_html,vitrine-ai-pro,factory.vitrineaipro.com.br,conhecasumare.com.br}\n'
        )
        if 'HOSTGATOR_SSH_HOST:' not in compose_text:
            if env_anchor not in compose_text:
                raise RuntimeError('Compose: marcador OPS_TIMEOUT não encontrado')
            compose_text = compose_text.replace(env_anchor, env_anchor + env_block, 1)
        compose.write_text(compose_text, encoding='utf-8')

    print('HOSTGATOR_REMOTE_OPS_PREPARED')
    print(f'BACKUP_STAMP={STAMP}')
    print('NEXT=mount SSH key as /run/secrets/hostgator_ops_key and rebuild connector once')


if __name__ == '__main__':
    main()
