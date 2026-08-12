from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

CONNECTOR_ROOT = Path('/srv/connectors/vitrine-vps-mcp')
COMPOSE_FILES = [
    'docker-compose.mcp.yml',
    'docker-compose.connector-v2.override.yml',
]
MCP_HEALTH_TIMEOUT = int(os.getenv('MCP_HEALTH_TIMEOUT', '180'))
MCP_HEALTH_INTERVAL = float(os.getenv('MCP_HEALTH_INTERVAL', '2'))


def run(command: list[str], cwd: Path | None = None, label: str | None = None) -> None:
    if label:
        print(f'GATE_START={label}', flush=True)
    print('+', ' '.join(command), flush=True)
    proc = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.stdout:
        print(proc.stdout.rstrip(), flush=True)
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr, flush=True)
    if proc.returncode != 0:
        if label:
            print(f'GATE_FAIL={label} EXIT={proc.returncode}', file=sys.stderr, flush=True)
        raise RuntimeError(f'{label or "command"} failed with exit {proc.returncode}: {" ".join(command)}')
    if label:
        print(f'GATE_PASS={label}', flush=True)


def capture(command: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f'command failed with exit {proc.returncode}: {" ".join(command)}')
    return proc.stdout.strip()


def backup_tree(source: Path) -> Path:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    target = Path('/srv/backups/vitrine-vps-mcp') / f'connector-{stamp}'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=True)
    return target


def compose_command(*args: str) -> list[str]:
    command = ['docker', 'compose']
    for compose_file in COMPOSE_FILES:
        command.extend(['-f', compose_file])
    command.extend(args)
    return command


def resolve_mcp_service_container() -> str:
    container_id = capture(
        compose_command('ps', '-q', 'vps_mcp_connector'),
        CONNECTOR_ROOT,
    ).splitlines()
    if len(container_id) != 1 or not container_id[0]:
        raise RuntimeError('mcp probe: running service container not found')
    return container_id[0]


def wait_for_mcp_health(container_id: str) -> None:
    print('GATE_START=mcp_service_health', flush=True)
    deadline = time.monotonic() + MCP_HEALTH_TIMEOUT
    last_status = ''
    while time.monotonic() < deadline:
        status = capture([
            'docker', 'inspect', '--format',
            '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}',
            container_id,
        ]).strip().lower()
        if status != last_status:
            print(f'MCP_HEALTH_STATUS={status}', flush=True)
            last_status = status
        if status == 'healthy':
            print('GATE_PASS=mcp_service_health', flush=True)
            return
        if status in {'dead', 'exited', 'removing'}:
            print(f'GATE_FAIL=mcp_service_health STATUS={status}', file=sys.stderr, flush=True)
            raise RuntimeError(f'mcp service became {status} before healthy')
        time.sleep(MCP_HEALTH_INTERVAL)
    print('GATE_FAIL=mcp_service_health EXIT=124', file=sys.stderr, flush=True)
    raise TimeoutError(f'mcp service did not become healthy within {MCP_HEALTH_TIMEOUT}s')


def _network_priority(name: str) -> tuple[int, str]:
    lowered = name.lower()
    if lowered == 'vitrine_mcp_internal':
        return 0, name
    if lowered.endswith('_mcp_internal'):
        return 1, name
    if 'internal' in lowered:
        return 2, name
    if 'egress' not in lowered:
        return 3, name
    return 4, name


def resolve_mcp_probe_runtime(container_id: str) -> tuple[str, str]:

    image = capture(
        ['docker', 'inspect', '--format', '{{.Config.Image}}', container_id],
    )
    network_output = capture(
        [
            'docker', 'inspect', '--format',
            '{{json .NetworkSettings.Networks}}',
            container_id,
        ],
    )
    try:
        network_settings = json.loads(network_output)
    except json.JSONDecodeError as exc:
        raise RuntimeError('mcp probe: invalid network inspection result') from exc
    networks = [
        name
        for name, settings in network_settings.items()
        if isinstance(settings, dict)
        and (
            'vps_mcp_connector' in (settings.get('Aliases') or [])
            or 'vitrine_vps_mcp_connector' in (settings.get('Aliases') or [])
        )
    ]
    network = min(networks, key=_network_priority) if networks else ''
    if not image or not network:
        raise RuntimeError('mcp probe: image or network could not be resolved')
    return image, network


def restore_backup(backup: Path) -> None:
    print('ROLLBACK_START=SIM', file=sys.stderr, flush=True)
    failed = CONNECTOR_ROOT.with_name(CONNECTOR_ROOT.name + '.failed')
    if failed.exists():
        shutil.rmtree(failed)
    if CONNECTOR_ROOT.exists():
        CONNECTOR_ROOT.rename(failed)
    shutil.copytree(backup, CONNECTOR_ROOT, symlinks=True)
    run(compose_command('build', '--no-cache'), CONNECTOR_ROOT, 'rollback_build')
    run(compose_command('up', '-d'), CONNECTOR_ROOT, 'rollback_up')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', default='https://github.com/cschibelsky-star/Vitrine-IA-Pro-VPS.git')
    parser.add_argument('--branch', default='fix/connector-stabilization-v2')
    parser.add_argument('--confirm', required=True)
    args = parser.parse_args()

    if args.confirm != 'EXECUTAR':
        raise SystemExit('Confirmação inválida. Use --confirm EXECUTAR')
    if not CONNECTOR_ROOT.is_dir():
        raise SystemExit(f'Conector não encontrado: {CONNECTOR_ROOT}')

    backup = backup_tree(CONNECTOR_ROOT)
    print(f'BACKUP={backup}', flush=True)

    try:
        with tempfile.TemporaryDirectory(prefix='vitrine-connector-release-') as temp:
            checkout = Path(temp) / 'source'
            run(['git', 'clone', '--depth', '1', '--branch', args.branch, args.repository, str(checkout)], label='source_clone')

            run([sys.executable, str(checkout / 'connector-v2' / 'test_connector_stabilization.py')], checkout, 'source_stabilization_test')
            run([sys.executable, str(checkout / 'bootstrap' / 'test_install_connector_release.py')], checkout, 'source_release_gate_test')
            run([sys.executable, str(checkout / 'project-manager' / 'test_install_project_manager.py')], checkout, 'source_project_manager_test')
            run([sys.executable, str(checkout / 'project-manager' / 'test_project_file_operations.py')], checkout, 'source_project_file_operations_test')
            run([sys.executable, '-m', 'py_compile',
                 str(checkout / 'connector-v2' / 'main_tvsumare_tools.py'),
                 str(checkout / 'connector-v2' / 'connector_runtime.py'),
                 str(checkout / 'connector-v2' / 'probe_streamable_http.py'),
                 str(checkout / 'connector-v2' / 'install_connector_v2.py'),
                 str(checkout / 'project-manager' / 'project_file_operations.py'),
                 str(checkout / 'project-manager' / 'project_manager_operations.py'),
                 str(checkout / 'project-manager' / 'project_manager_tools.py'),
                 str(checkout / 'project-manager' / 'test_project_file_operations.py'),
                 str(checkout / 'project-manager' / 'project_deployment_engine.py')], label='source_py_compile')

            run([sys.executable, str(checkout / 'connector-v2' / 'install_connector_v2.py')], label='install_connector_v2')
            run([sys.executable, str(checkout / 'project-manager' / 'install_project_manager.py')], label='install_project_manager')

            run([
                sys.executable, '-m', 'py_compile',
                str(CONNECTOR_ROOT / 'ops_broker.py'),
                str(CONNECTOR_ROOT / 'main.py'),
                str(CONNECTOR_ROOT / 'connector_runtime.py'),
                str(CONNECTOR_ROOT / 'tvsumare_operations.py'),
                str(CONNECTOR_ROOT / 'tvsumare_tools.py'),
                str(CONNECTOR_ROOT / 'project_file_operations.py'),
                str(CONNECTOR_ROOT / 'project_manager_operations.py'),
                str(CONNECTOR_ROOT / 'project_manager_tools.py'),
                str(CONNECTOR_ROOT / 'project_deployment_engine.py'),
            ], label='installed_py_compile')

            run(compose_command('config', '--quiet'), CONNECTOR_ROOT, 'compose_config')
            run(compose_command('build', '--no-cache'), CONNECTOR_ROOT, 'compose_build')
            run(compose_command('up', '-d'), CONNECTOR_ROOT, 'compose_up')
            run(compose_command('ps', '-a'), CONNECTOR_ROOT, 'compose_ps')

            run(['docker', 'exec', 'vitrine_mcp_ops_broker', 'python', '-c',
                 'import project_deployment_engine, project_manager_operations, tvsumare_operations; print("OPS_BROKER_IMPORTS=PASS")'],
                label='ops_broker_imports')

            mcp_container_id = resolve_mcp_service_container()
            wait_for_mcp_health(mcp_container_id)
            probe_image, probe_network = resolve_mcp_probe_runtime(mcp_container_id)
            print('SHARED_NETWORK_RESOLUTION_PASS', flush=True)
            run([
                'docker', 'run', '--rm',
                '--network', probe_network,
                '--entrypoint', 'python',
                probe_image,
                '-c',
                'import socket; socket.create_connection(("vps_mcp_connector", 8765), timeout=10).close(); print("PROBE_TCP_CONNECT=PASS")',
            ], label='probe_tcp_connect')
            run([
                'docker', 'run', '--rm',
                '--network', probe_network,
                '--entrypoint', 'python',
                probe_image,
                '/app/probe_streamable_http.py',
                '--url', 'http://vps_mcp_connector:8765/mcp',
                '--calls', '0',
                '--sessions', '1',
                '--catalog-only',
                '--require-tool', 'project_deploy',
                '--require-tool', 'connector_health',
                '--require-tool', 'project_context',
                '--require-tool', 'project_write_file',
                '--require-tool', 'project_php_lint',
            ], label='mcp_protocol_registry')
            print('MCP_PROTOCOL_REGISTRY_PASS', flush=True)

        print('CONNECTOR_RELEASE_INSTALLED=SIM')
        return 0
    except Exception as exc:
        print(f'INSTALLATION_FAILED={exc}', file=sys.stderr, flush=True)
        restore_backup(backup)
        print('ROLLBACK_COMPLETED=SIM', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
