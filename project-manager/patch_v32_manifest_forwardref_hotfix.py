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

    backup = TARGET.with_name(f'{TARGET.name}.backup-manifest-forwardref-{STAMP}')
    shutil.copy2(TARGET, backup)

    text = TARGET.read_text(encoding='utf-8')

    old = 'def project_manifest_create(req: ProjectManifestCreateRequest = Body(...)) -> dict[str, Any]:\n    if req.confirm != "EXECUTAR":\n'
    new = 'def project_manifest_create(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:\n    req = ProjectManifestCreateRequest.model_validate(payload)\n    if req.confirm != "EXECUTAR":\n'

    if new not in text:
        if old not in text:
            raise RuntimeError('Assinatura esperada do project_manifest_create nao encontrada')
        text = text.replace(old, new, 1)

    TARGET.write_text(text, encoding='utf-8')

    print('V32_MANIFEST_FORWARDREF_HOTFIX_PATCHED')
    print(f'BACKUP={backup}')
    print('NEXT=python3 -m py_compile project_manager_operations.py')
    print('NEXT=docker compose -f docker-compose.mcp.yml up -d --build')


if __name__ == '__main__':
    main()
