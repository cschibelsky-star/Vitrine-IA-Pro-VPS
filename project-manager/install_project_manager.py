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

    import_block = '''\nfrom project_manager_tools import (\n    project_manifest as _project_manifest,\n    project_workspace as _project_workspace,\n    project_clone as _project_clone,\n    project_status as _project_status,\n)\n'''

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

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_manifest(project_id: str) -> dict[str, Any]:\n    return _project_manifest(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_workspace(project_id: str) -> dict[str, Any]:\n    return _project_workspace(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef project_clone(project_id: str) -> dict[str, Any]:\n    return _project_clone(project_id)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef project_status(project_id: str) -> dict[str, Any]:\n    return _project_status(project_id)\n'''

    text = ensure_block_before(
        text,
        '\nif __name__ == "__main__":\n',
        tools_block,
        'def project_clone(project_id:',
        'registro project manager tools',
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

    print('PROJECT_MANAGER_INSTALLED')
    print(f'BACKUP_STAMP={STAMP}')


if __name__ == '__main__':
    main()
