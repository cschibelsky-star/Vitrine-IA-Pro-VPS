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
    return text


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f'Raiz do conector não encontrada: {ROOT}')

    manifest_source = SOURCE / 'manifests'
    manifest_target = ROOT / 'project-manifests'
    manifest_target.mkdir(parents=True, exist_ok=True)

    for item in (
        'project_manager_operations.py',
        'project_file_operations.py',
        'project_manager_tools.py',
        'project_deployment_engine.py',
        'project_read_operations.py',
        'project_shared_operations.py',
    ):
        source = SOURCE / item
        if source.exists():
            shutil.copy2(source, ROOT / item)

    for manifest in manifest_source.glob('*.json'):
        shutil.copy2(manifest, manifest_target / manifest.name)

    print('PROJECT_MANAGER_INSTALLED_V4')
    print(f'BACKUP_STAMP={STAMP}')


if __name__ == '__main__':
    main()
