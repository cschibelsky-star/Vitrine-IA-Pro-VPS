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

    backup = TARGET.with_name(f'{TARGET.name}.backup-manifest-model-{STAMP}')
    shutil.copy2(TARGET, backup)

    text = TARGET.read_text(encoding='utf-8')

    if 'class ProjectManifestCreateRequest(BaseModel):' not in text:
        marker = 'class ProjectReadRequest(BaseModel):\n    project_id: str\n    path: str\n    start_line: int = 1\n    end_line: int = 400\n'
        if marker not in text:
            raise RuntimeError('ProjectReadRequest esperado nao encontrado')
        block = marker + '''\n\nclass ProjectManifestCreateRequest(BaseModel):\n    project_id: str\n    name: str\n    workspace_root: str\n    repository_url: str\n    branch: str = "main"\n    repository_directory: str = "repository"\n    shared_directories: list[str] = []\n    compose_file: str = ""\n    docker_project: str = ""\n    release_directory: str = "releases"\n    confirm: str = ""\n'''
        text = text.replace(marker, block, 1)

    TARGET.write_text(text, encoding='utf-8')

    print('V32_MANIFEST_MODEL_HOTFIX_PATCHED')
    print(f'BACKUP={backup}')
    print('NEXT=python3 -m py_compile project_manager_operations.py')
    print('NEXT=docker compose -f docker-compose.mcp.yml up -d --build')


if __name__ == '__main__':
    main()
