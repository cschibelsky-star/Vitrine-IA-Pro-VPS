"""Preserve live connector extensions; prepare all patches before any write."""
import ast
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

ROUTE = '''

@router.get('/heygen/runtime-inventory', dependencies=[Depends(auth)])
def heygen_runtime_inventory(environment: str = 'production') -> dict[str, Any]:
    from heygen_runtime_audit import inventory
    result = inventory(environment)
    audit('heygen_runtime_inventory', {'environment': environment}, result)
    return result
'''
CLIENT = '''

def tvsumare_heygen_runtime_inventory(environment: str = 'production') -> dict[str, Any]:
    if environment not in {'production', 'homologation'}:
        return {'ok': False, 'error': 'environment_not_allowed'}
    return _request('GET', '/tvsumare/heygen/runtime-inventory?environment=' + environment,
                    timeout=70)
'''
REGISTRATION = '''

@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def tvsumare_heygen_runtime_inventory(environment: str = 'production') -> dict[str, Any]:
    from tvsumare_tools import tvsumare_heygen_runtime_inventory as inventory
    return inventory(environment)
'''


def plan(root: Path, source: Path) -> dict:
    root = root.resolve()
    patches = {}
    specs = [('tvsumare_operations.py', ROUTE, 'def auth('),
             ('tvsumare_tools.py', CLIENT, 'def _request('),
             ('main.py', REGISTRATION, '@mcp.tool(')]
    for name, block, required in specs:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('unsafe_or_missing_target:' + name)
        old = path.read_text()
        if required not in old:
            raise ValueError('incompatible_target:' + name)
        tree = ast.parse(old)
        matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == 'tvsumare_heygen_runtime_inventory']
        if name == 'tvsumare_operations.py':
            matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'heygen_runtime_inventory']
        if matches:
            # An installed implementation must be reviewed, never silently replaced.
            if block.strip() not in old:
                raise ValueError('existing_implementation_requires_review:' + name)
            continue
        guard = '\nif __name__ == "__main__":'
        new = old.replace(guard, block + guard, 1) if guard in old else old + block
        ast.parse(new)
        patches[path] = new.encode()
    module = (source / 'heygen_runtime_audit.py').read_bytes()
    ast.parse(module)
    target = root / 'heygen_runtime_audit.py'
    if target.is_symlink():
        raise ValueError('unsafe_module_target')
    if target.exists() and target.read_bytes() != module:
        raise ValueError('existing_module_requires_review')
    if not target.exists():
        patches[target] = module
    docker = root / 'Dockerfile'
    if docker.is_symlink() or not docker.is_file():
        raise ValueError('unsafe_or_missing_dockerfile')
    old = docker.read_text()
    line = 'COPY heygen_runtime_audit.py ./\n'
    if line not in old:
        if old.count('\nFROM ') or not old.lstrip().startswith('FROM '):
            raise ValueError('dockerfile_requires_review')
        patches[docker] = (old.rstrip() + '\n' + line).encode()
    return patches


def apply(root: Path, source: Path) -> dict:
    patches = plan(root, source)
    if not patches:
        return {'status': 'already_installed'}
    backup = Path(tempfile.mkdtemp(prefix='heygen-inventory-backup-', dir=root))
    originals = {}
    for path in patches:
        originals[path] = path.read_bytes() if path.exists() else None
        if path.exists():
            shutil.copy2(path, backup / path.name)
    changed = []
    try:
        for path, data in patches.items():
            fd, temp = tempfile.mkstemp(prefix='.heygen-', dir=root)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(data)
                if path.exists():
                    shutil.copystat(path, temp)
                    st = path.stat()
                    os.chown(temp, st.st_uid, st.st_gid)
                else:
                    os.chmod(temp, 0o644)
                os.replace(temp, path)
                changed.append(path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
    except Exception:
        for path in reversed(changed):
            if originals[path] is None:
                path.unlink()
            else:
                shutil.copy2(backup / path.name, path)
        raise
    return {'status': 'installed_not_activated', 'backup': str(backup),
            'files': {p.name: hashlib.sha256(data).hexdigest() for p, data in patches.items()}}


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/srv/connectors/vitrine-vps-mcp'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    source = Path(__file__).parent
    if args.apply:
        print(json.dumps(apply(args.root, source)))
    else:
        print(json.dumps({'status': 'dry_run', 'files': [p.name for p in plan(args.root, source)]}))
