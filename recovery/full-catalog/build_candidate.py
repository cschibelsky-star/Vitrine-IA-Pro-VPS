from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ACTIVE_ROOTS = {
    Path('/srv/connectors/vitrine-vps-mcp').resolve(),
    Path('/srv/connectors/vitrine-vps-mcp-main').resolve(),
}

HERE = Path(__file__).resolve().parent


def require_safe_candidate_root(raw: str) -> Path:
    root = Path(raw).resolve()
    if root in ACTIVE_ROOTS:
        raise SystemExit('REFUSED: active connector root is not a candidate target')
    if not str(root).startswith('/srv/connectors/'):
        raise SystemExit('REFUSED: candidate root must be under /srv/connectors')
    if 'candidate' not in root.name:
        raise SystemExit('REFUSED: candidate root name must contain candidate')
    return root


def copy_if_present(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    shutil.copy2(source, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-root', required=True)
    parser.add_argument('--candidate-root', default='/srv/connectors/vitrine-vps-mcp-candidate-full-catalog')
    args = parser.parse_args()

    base = Path(args.base_root).resolve()
    candidate = require_safe_candidate_root(args.candidate_root)
    if not base.is_dir():
        raise SystemExit(f'base root not found: {base}')
    if candidate.exists():
        raise SystemExit(f'REFUSED: candidate already exists: {candidate}')

    shutil.copytree(base, candidate, symlinks=True)

    historical = {
        'supervisor.py': HERE / 'supervisor.py',
        'workflow_catalog.py': HERE / 'workflow_catalog.py',
    }
    for name, source in historical.items():
        copy_if_present(source, candidate / name)

    manifest = json.loads((HERE / 'CATALOG_RECONSTRUCTION.json').read_text(encoding='utf-8'))
    (candidate / 'CATALOG_RECONSTRUCTION.json').write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )

    print(f'CANDIDATE_ROOT={candidate}')
    print('ACTIVE_RUNTIME_CHANGED=NO')
    print('CUTOVER_PERFORMED=NO')
    print('NEXT=complete pinned historical layers, compile, then run tools/list gate')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
