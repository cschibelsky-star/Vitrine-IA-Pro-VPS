#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys

CONF = Path('/srv/vitrine/docker/nginx/conf.d/mcp-v5.conf')
STATIC = 'proxy_pass http://vitrine_mcp_v5:8000/mcp;'
DYNAMIC = '''resolver 127.0.0.11 valid=10s ipv6=off;\n        set $mcp_v5_backend vitrine_mcp_v5;\n        proxy_pass http://$mcp_v5_backend:8000/mcp;'''


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def main() -> int:
    if not CONF.is_file():
        raise SystemExit(f'ABORTADO: arquivo nao encontrado: {CONF}')

    original = CONF.read_text()

    if DYNAMIC in original:
        print('JA_ENDURECIDO')
        return 0

    count = original.count(STATIC)
    if count != 1:
        raise SystemExit(f'ABORTADO: proxy_pass esperado encontrado {count} vezes')

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = CONF.with_name(f'{CONF.name}.bak-{stamp}')
    shutil.copy2(CONF, backup)

    updated = original.replace(STATIC, DYNAMIC, 1)
    tmp = CONF.with_name(f'.{CONF.name}.tmp-{stamp}')
    tmp.write_text(updated)
    tmp.replace(CONF)

    try:
        run('docker', 'exec', 'vitrine_nginx', 'nginx', '-t')
        run('docker', 'exec', 'vitrine_nginx', 'nginx', '-s', 'reload')
    except Exception:
        shutil.copy2(backup, CONF)
        try:
            run('docker', 'exec', 'vitrine_nginx', 'nginx', '-t')
            run('docker', 'exec', 'vitrine_nginx', 'nginx', '-s', 'reload')
        finally:
            print(f'ROLLBACK={backup}', file=sys.stderr)
        raise

    print('PATCH_APLICADO')
    print(f'BACKUP={backup}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
