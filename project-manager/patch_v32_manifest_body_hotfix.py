from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
TARGET = ROOT / 'project_manager_operations.py'
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def main() -> None:
    if not TARGET.is_file():
        raise SystemExit(f'Arquivo nao encontrado: {TARGET}')

    backup = TARGET.with_name(f'{TARGET.name}.backup-manifest-body-{STAMP}')
    shutil.copy2(TARGET, backup)

    text = TARGET.read_text(encoding='utf-8')

    old_import = 'from fastapi import APIRouter, Depends, Header, HTTPException\n'
    new_import = 'from fastapi import APIRouter, Body, Depends, Header, HTTPException\n'
    if new_import not in text:
        if old_import not in text:
            raise RuntimeError('Import FastAPI esperado nao encontrado')
        text = text.replace(old_import, new_import, 1)

    old_signature = 'def project_manifest_create(req: ProjectManifestCreateRequest) -> dict[str, Any]:\n'
    new_signature = 'def project_manifest_create(req: ProjectManifestCreateRequest = Body(...)) -> dict[str, Any]:\n'
    if new_signature not in text:
        if old_signature not in text:
            raise RuntimeError('Assinatura project_manifest_create esperada nao encontrada')
        text = text.replace(old_signature, new_signature, 1)

    TARGET.write_text(text, encoding='utf-8')

    print('V32_MANIFEST_BODY_HOTFIX_PATCHED')
    print(f'BACKUP={backup}')
    print('NEXT=python3 -m py_compile project_manager_operations.py')
    print('NEXT=docker compose -f docker-compose.mcp.yml up -d --build')


if __name__ == '__main__':
    main()
