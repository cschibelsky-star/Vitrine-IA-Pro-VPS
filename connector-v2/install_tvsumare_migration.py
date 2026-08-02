from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.backup-tvsumare-migration-{STAMP}'))


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

    for source_name, target_name in (
        ('tvsumare_migration_operations.py', 'tvsumare_migration_operations.py'),
        ('tvsumare_migration_tools.py', 'tvsumare_migration_tools.py'),
    ):
        source = SOURCE / source_name
        target = ROOT / target_name
        if not source.exists():
            raise SystemExit(f'Arquivo fonte ausente: {source}')
        shutil.copy2(source, target)

    ops_broker = ROOT / 'ops_broker.py'
    backup(ops_broker)
    text = ops_broker.read_text(encoding='utf-8')
    text = ensure_line_after(
        text,
        'from tvsumare_operations import router as tvsumare_operations_router\n',
        'from tvsumare_migration_operations import router as tvsumare_migration_router\n',
        'import migration router',
    )
    text = ensure_line_after(
        text,
        'app.include_router(tvsumare_operations_router)\n',
        'app.include_router(tvsumare_migration_router)\n',
        'include migration router',
    )
    ops_broker.write_text(text, encoding='utf-8')

    main_py = ROOT / 'main.py'
    backup(main_py)
    text = main_py.read_text(encoding='utf-8')
    import_block = '''\nfrom tvsumare_migration_tools import (\n    tvsumare_clone_repository as _tvsumare_clone_repository,\n    tvsumare_import_hostgator_snapshot as _tvsumare_import_hostgator_snapshot,\n)\n'''
    if 'from tvsumare_migration_tools import' not in text:
        anchor = 'from tvsumare_tools import ('
        index = text.find(anchor)
        if index == -1:
            raise RuntimeError('imports migration tools: marcador tvsumare_tools não encontrado')
        end = text.find(')\n', index)
        if end == -1:
            raise RuntimeError('imports migration tools: fechamento não encontrado')
        end += 2
        text = text[:end] + import_block + text[end:]

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_clone_repository(\n    repository_url: str = "https://github.com/cschibelsky-star/TVSUMARE_ENTERPRISE.git",\n    branch: str = "main",\n) -> dict[str, Any]:\n    return _tvsumare_clone_repository(repository_url, branch)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef tvsumare_import_hostgator_snapshot(\n    remote_path: str = "public_html",\n) -> dict[str, Any]:\n    return _tvsumare_import_hostgator_snapshot(remote_path)\n'''
    text = ensure_block_before(
        text,
        '\nif __name__ == "__main__":\n',
        tools_block,
        'def tvsumare_clone_repository(',
        'registro ferramentas migração',
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
        raise RuntimeError('Dockerfile: linha COPY de módulos não encontrada')

    required = ['tvsumare_migration_operations.py', 'tvsumare_migration_tools.py']
    updated_line = copy_line
    for item in required:
        if item not in updated_line.split():
            updated_line = updated_line[:-3] + f' {item} ./'
    docker_text = docker_text.replace(copy_line, updated_line, 1)
    dockerfile.write_text(docker_text, encoding='utf-8')

    print('TVSUMARE_MIGRATION_CONNECTOR_INSTALLED')
    print(f'BACKUP_STAMP={STAMP}')


if __name__ == '__main__':
    main()
