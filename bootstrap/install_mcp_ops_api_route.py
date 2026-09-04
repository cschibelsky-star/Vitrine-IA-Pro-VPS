from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

LIVE_ROOT = Path('/srv/connectors/vitrine-vps-mcp')
REPO_ROOT = Path('/srv/projects/vitrine-vps-mcp/repository')
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.backup-ops-api-route-{STAMP}'))


def run(command: list[str], cwd: Path) -> None:
    proc = subprocess.run(command, cwd=str(cwd), text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def main() -> None:
    if not LIVE_ROOT.is_dir():
        raise SystemExit(f'Live connector not found: {LIVE_ROOT}')
    if not REPO_ROOT.is_dir():
        raise SystemExit(f'Repository not found: {REPO_ROOT}')

    source_tools = REPO_ROOT / 'project-manager' / 'project_manager_tools.py'
    target_tools = LIVE_ROOT / 'project_manager_tools.py'
    compose = LIVE_ROOT / 'docker-compose.mcp.yml'

    for required in (source_tools, target_tools, compose):
        if not required.exists():
            raise SystemExit(f'Required path not found: {required}')

    backup(target_tools)
    backup(compose)
    shutil.copy2(source_tools, target_tools)

    text = compose.read_text(encoding='utf-8')

    if 'OPS_API_URL:' not in text:
        marker = '      OPS_BROKER_URL: http://ops_broker:8770\n'
        if marker not in text:
            raise SystemExit('Compose marker OPS_BROKER_URL not found')
        text = text.replace(
            marker,
            marker
            + '      OPS_API_URL: http://host.docker.internal:18080\n'
            + '      OPS_API_FALLBACK: "1"\n',
            1,
        )

    service_marker = '  vps_mcp_connector:\n'
    if service_marker not in text:
        raise SystemExit('Compose service vps_mcp_connector not found')

    service_start = text.index(service_marker)
    tail = text[service_start:]
    if '    extra_hosts:\n      - "host.docker.internal:host-gateway"\n' not in tail:
        environment_marker = '    environment:\n'
        relative = tail.find(environment_marker)
        if relative == -1:
            raise SystemExit('vps_mcp_connector environment block not found')
        insertion = service_start + relative
        text = (
            text[:insertion]
            + '    extra_hosts:\n'
            + '      - "host.docker.internal:host-gateway"\n'
            + text[insertion:]
        )

    compose.write_text(text, encoding='utf-8')

    run(['python3', '-m', 'py_compile', 'project_manager_tools.py'], LIVE_ROOT)
    run(['docker', 'compose', '-f', 'docker-compose.mcp.yml', 'config', '-q'], LIVE_ROOT)
    run(['docker', 'compose', '-f', 'docker-compose.mcp.yml', 'up', '-d', '--build', 'vps_mcp_connector'], LIVE_ROOT)

    print('MCP_OPS_API_ROUTE_INSTALLED=SIM')
    print(f'BACKUP_STAMP={STAMP}')
    print('OPS_API_URL=http://host.docker.internal:18080')
    print('OPS_API_FALLBACK=1')


if __name__ == '__main__':
    main()
