from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
TARGET = ROOT / 'docker-compose.mcp.yml'
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')
LINE = '      PROJECT_WORKSPACE_ROOTS: /srv/tvsumare,/srv/projects\n'
ANCHOR = '      PROJECT_MANIFEST_ROOT: /srv/connectors/vitrine-vps-mcp/project-manifests\n'


def main() -> None:
    if not TARGET.is_file():
        raise SystemExit(f'Arquivo nao encontrado: {TARGET}')

    text = TARGET.read_text(encoding='utf-8')
    if LINE in text:
        print('V32_COMPOSE_WORKSPACE_ENV_ALREADY_PATCHED')
        return
    if ANCHOR not in text:
        raise RuntimeError('Anchor PROJECT_MANIFEST_ROOT nao encontrado; nenhuma alteracao aplicada')

    backup = TARGET.with_name(f'{TARGET.name}.backup-workspace-env-{STAMP}')
    shutil.copy2(TARGET, backup)
    TARGET.write_text(text.replace(ANCHOR, ANCHOR + LINE, 1), encoding='utf-8')

    print('V32_COMPOSE_WORKSPACE_ENV_PATCHED')
    print(f'BACKUP={backup}')
    print('NEXT=docker compose -f docker-compose.mcp.yml config | grep PROJECT_WORKSPACE_ROOTS')
    print('NEXT=docker compose -f docker-compose.mcp.yml up -d --build')


if __name__ == '__main__':
    main()
