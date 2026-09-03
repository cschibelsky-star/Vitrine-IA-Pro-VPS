from __future__ import annotations

import re
from pathlib import Path

import install_project_manager

RUNTIME_OVERRIDE = Path('/runtime/docker-compose.connector-v2.override.yml')
CANONICAL = (
    'PROJECT_DOCKER_ALLOWED_PREFIXES: '
    'vitrine_core_,cursos_ia_mvp_,tvsumare_,agente_compras_,'
    'vitrine_marketing_,vitrine_factory_,studio_,vitrine_social_'
)


def normalize_runtime_override() -> None:
    if not RUNTIME_OVERRIDE.is_file():
        return

    text = RUNTIME_OVERRIDE.read_text(encoding='utf-8')
    lines = text.splitlines()
    output: list[str] = []
    inserted = False

    for line in lines:
        if re.match(r'^\s{6}PROJECT_DOCKER_ALLOWED_PREFIXES:', line):
            if not inserted:
                output.append(f'      {CANONICAL}')
                inserted = True
            continue
        output.append(line)

    if not inserted:
        raise RuntimeError('PROJECT_DOCKER_ALLOWED_PREFIXES anchor not found in runtime override')

    RUNTIME_OVERRIDE.write_text('\n'.join(output) + '\n', encoding='utf-8')


def main() -> None:
    normalize_runtime_override()
    install_project_manager.main()
    normalize_runtime_override()
    print('PROJECT_MANAGER_SAFE_INSTALL_OK')


if __name__ == '__main__':
    main()
