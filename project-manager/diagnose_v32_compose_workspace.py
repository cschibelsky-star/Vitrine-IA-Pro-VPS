from __future__ import annotations

from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
NEEDLES = ('workspace_not_allowed', 'project_compose_manage', 'compose_manage', 'PROJECT_WORKSPACE_ROOTS')


def print_context(path: Path, lines: list[str], index: int, radius: int = 12) -> None:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    print(f'\n=== {path} : linhas {start + 1}-{end} ===')
    for pos in range(start, end):
        marker = '>>' if pos == index else '  '
        print(f'{marker} {pos + 1:04d}: {lines[pos]}')


def main() -> None:
    if not ROOT.is_dir():
        raise SystemExit(f'Conector nao encontrado: {ROOT}')

    matches = 0
    for path in sorted(ROOT.glob('*.py')):
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError:
            continue
        for index, line in enumerate(lines):
            if any(needle in line for needle in NEEDLES):
                print_context(path, lines, index)
                matches += 1

    for path in sorted(ROOT.glob('docker-compose*.yml')):
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError:
            continue
        for index, line in enumerate(lines):
            if 'PROJECT_WORKSPACE_ROOTS' in line or '/srv/tvsumare' in line or '/srv/projects' in line:
                print_context(path, lines, index, radius=6)
                matches += 1

    print(f'\nMATCHES={matches}')
    if matches == 0:
        print('Nenhuma ocorrencia encontrada; verificar codigo gerado ou modulo fora da raiz principal.')


if __name__ == '__main__':
    main()
