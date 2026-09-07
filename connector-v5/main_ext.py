from __future__ import annotations

import hashlib
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from marketing_live_patch import apply as apply_marketing_live_patch
from controlled_operations_patch import apply as apply_controlled_operations_patch

main_path = Path('/app/main.py')
if not main_path.is_file():
    raise RuntimeError('main_py_missing')

source = main_path.read_text(encoding='utf-8')
source = apply_marketing_live_patch(source)
source = apply_controlled_operations_patch(source)

core = types.ModuleType('main')
core.__file__ = str(main_path)
sys.modules['main'] = core
exec(compile(source, str(main_path), 'exec'), core.__dict__)

# main.py remains the single registry for V5 tools. The source is patched only
# in memory so the container filesystem can stay read-only.
mcp = core.mcp


INVENTORY_ROOTS = (
    Path('/srv/projects'),
    Path('/srv/tvsumare'),
    Path('/srv/backups'),
    Path('/srv/connectors'),
    Path('/srv-backupzip'),
)
INVENTORY_EXCLUDED_DIR_NAMES = {
    '.git', 'vendor', 'node_modules', '__pycache__', 'secrets', 'credentials',
    'private', '.cache', 'cache', 'storage/logs', 'storage/oauth',
}
INVENTORY_MAX_FILES_PER_ENTRY = 50000
INVENTORY_MAX_DIRS_PER_ENTRY = 10000
INVENTORY_MAX_TOP_LEVEL_ENTRIES = 500
INVENTORY_MAX_ARCHIVES = 500
INVENTORY_MAX_HASH_BYTES_TOTAL = 20 * 1024 * 1024 * 1024


def _inventory_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _inventory_branch(path: Path) -> str:
    head = path / '.git' / 'HEAD'
    try:
        raw = head.read_text(encoding='utf-8', errors='replace').strip()
    except OSError:
        return ''
    prefix = 'ref: refs/heads/'
    if raw.startswith(prefix):
        return raw[len(prefix):]
    return raw[:40] if raw else ''


def _inventory_registered_workspaces() -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        manifests = sorted(core.MANIFEST_ROOT.glob('*.json'))
    except OSError:
        return result
    for manifest_path in manifests:
        try:
            data = json.loads(manifest_path.read_text(encoding='utf-8'))
            project_id = str(data.get('id', '')).strip()
            workspace_root = str(data.get('workspace_root', '')).strip()
            if project_id and workspace_root:
                result[str(Path(workspace_root).resolve())] = project_id
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return result


def _inventory_tree_stats(root: Path) -> dict[str, object]:
    files = 0
    dirs = 0
    total_bytes = 0
    latest_mtime = 0.0
    truncated = False
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    name = entry.name
                    if name in INVENTORY_EXCLUDED_DIR_NAMES:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            dirs += 1
                            if dirs > INVENTORY_MAX_DIRS_PER_ENTRY:
                                truncated = True
                                continue
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            files += 1
                            st = entry.stat(follow_symlinks=False)
                            total_bytes += int(st.st_size)
                            latest_mtime = max(latest_mtime, float(st.st_mtime))
                            if files >= INVENTORY_MAX_FILES_PER_ENTRY:
                                truncated = True
                                stack.clear()
                                break
                    except OSError:
                        continue
        except OSError:
            continue
    return {
        'files': files,
        'dirs': dirs,
        'bytes': total_bytes,
        'latest_mtime': _inventory_iso(latest_mtime) if latest_mtime else None,
        'truncated': truncated,
    }


def _inventory_entry(path: Path, registered: dict[str, str], category: str) -> dict[str, object]:
    resolved = str(path.resolve())
    stats = _inventory_tree_stats(path)
    return {
        'name': path.name,
        'path': resolved,
        'category': category,
        'project_id': registered.get(resolved),
        'registered': resolved in registered,
        'git': (path / '.git').is_dir(),
        'branch': _inventory_branch(path),
        **stats,
    }


def _inventory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


@mcp.tool(annotations={'readOnlyHint': True, 'destructiveHint': False})
def vps_global_inventory() -> dict[str, object]:
    """Read-only inventory of fixed Vitrine IA Pro VPS roots; never reads file contents or secrets."""
    registered = _inventory_registered_workspaces()
    entries: list[dict[str, object]] = []
    archives: list[dict[str, object]] = []
    warnings: list[str] = []

    for base in INVENTORY_ROOTS:
        if not base.exists():
            warnings.append(f'missing_root:{base}')
            continue
        if base == Path('/srv/tvsumare'):
            entries.append(_inventory_entry(base, registered, 'project'))
            continue
        if base == Path('/srv-backupzip'):
            continue
        try:
            children = sorted(
                (p for p in base.iterdir() if p.is_dir()),
                key=lambda p: p.name.lower(),
            )[:INVENTORY_MAX_TOP_LEVEL_ENTRIES]
        except OSError as exc:
            warnings.append(f'root_unreadable:{base}:{type(exc).__name__}')
            continue
        category = 'backup' if base == Path('/srv/backups') else ('connector' if base == Path('/srv/connectors') else 'project')
        for child in children:
            entries.append(_inventory_entry(child, registered, category))

    archive_root = Path('/srv-backupzip')
    hashed_bytes = 0
    if archive_root.is_dir():
        try:
            zip_files = sorted(
                (p for p in archive_root.iterdir() if p.is_file() and p.suffix.lower() == '.zip'),
                key=lambda p: p.name.lower(),
            )[:INVENTORY_MAX_ARCHIVES]
        except OSError as exc:
            warnings.append(f'archive_root_unreadable:{type(exc).__name__}')
            zip_files = []
        for item in zip_files:
            try:
                st = item.stat()
                size = int(st.st_size)
                sha256 = None
                hash_skipped = False
                if hashed_bytes + size <= INVENTORY_MAX_HASH_BYTES_TOTAL:
                    sha256 = _inventory_sha256(item)
                    hashed_bytes += size
                else:
                    hash_skipped = True
                archives.append({
                    'name': item.name,
                    'path': str(item.resolve()),
                    'bytes': size,
                    'mtime': _inventory_iso(float(st.st_mtime)),
                    'sha256': sha256,
                    'hash_skipped': hash_skipped,
                })
            except OSError as exc:
                warnings.append(f'archive_unreadable:{item.name}:{type(exc).__name__}')

    known_paths = set(registered)
    seen_registered = {str(Path(str(e['path'])).resolve()) for e in entries if e.get('registered')}
    missing_registered = [
        {'project_id': project_id, 'workspace_root': workspace_root}
        for workspace_root, project_id in sorted(registered.items(), key=lambda kv: kv[1])
        if workspace_root not in seen_registered and workspace_root in known_paths
    ]

    summary = {
        'entries': len(entries),
        'registered_entries': sum(1 for e in entries if e.get('registered')),
        'orphan_entries': sum(1 for e in entries if not e.get('registered') and e.get('category') in {'project', 'connector'}),
        'backup_entries': sum(1 for e in entries if e.get('category') == 'backup'),
        'archives': len(archives),
        'archives_hashed_bytes': hashed_bytes,
    }
    return {
        'ok': True,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'roots': [str(p) for p in INVENTORY_ROOTS],
        'summary': summary,
        'entries': entries,
        'archives': archives,
        'registered_workspaces_not_seen': missing_registered,
        'warnings': warnings,
    }


if __name__ == '__main__':
    mcp.run(transport='http', host='0.0.0.0', port=8000)
