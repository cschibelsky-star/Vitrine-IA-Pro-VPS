from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
SOURCE = Path(__file__).resolve().parent.parent / 'connector-v2' / 'docker-compose.connector-v2.override.yml'
TARGET = ROOT / 'docker-compose.connector-v2.override.yml'
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f'Raiz do conector nao encontrada: {ROOT}')
    if not SOURCE.is_file():
        raise SystemExit(f'Template nao encontrado: {SOURCE}')

    if TARGET.exists():
        backup = TARGET.with_name(f'{TARGET.name}.backup-repair-{STAMP}')
        shutil.copy2(TARGET, backup)
        print(f'BACKUP={backup}')

    text = SOURCE.read_text(encoding='utf-8')
    anchor = '      PROJECT_MANAGER_TIMEOUT: 1200\n'
    extra = (
        '      PROJECT_MANIFEST_ROOT: /app/project-manifests\n'
        '      PROJECT_DOCKER_ALLOWED_PREFIXES: vitrine_core_,cursos_ia_mvp_,tvsumare_,agente_compras_\n'
    )
    if anchor not in text:
        raise SystemExit('Marcador PROJECT_MANAGER_TIMEOUT nao encontrado no template')
    if 'PROJECT_MANIFEST_ROOT:' not in text:
        text = text.replace(anchor, anchor + extra, 1)

    TARGET.write_text(text, encoding='utf-8')
    print('CONNECTOR_COMPOSE_OVERRIDE_REPAIRED')
    print(f'TARGET={TARGET}')


if __name__ == '__main__':
    main()
