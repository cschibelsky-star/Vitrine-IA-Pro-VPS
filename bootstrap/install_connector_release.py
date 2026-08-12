from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

CONNECTOR_ROOT = Path('/srv/connectors/vitrine-vps-mcp')
COMPOSE_FILES = [
    'docker-compose.mcp.yml',
    'docker-compose.connector-v2.override.yml',
]


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
                str(CONNECTOR_ROOT / 'project_manager_operations.py'),
                str(CONNECTOR_ROOT / 'project_manager_tools.py'),
                str(CONNECTOR_ROOT / 'project_deployment_engine.py'),
            ], label='installed_py_compile')

            run(compose_command('config'), CONNECTOR_ROOT, 'compose_config')
            run(compose_command('build', '--no-cache'), CONNECTOR_ROOT, 'compose_build')
            run(compose_command('up', '-d'), CONNECTOR_ROOT, 'compose_up')
            run(compose_command('ps', '-a'), CONNECTOR_ROOT, 'compose_ps')

            run(['docker', 'exec', 'vitrine_mcp_ops_broker', 'python', '-c',
                 'import project_deployment_engine, project_manager_operations, tvsumare_operations; print("OPS_BROKER_IMPORTS=PASS")'],
                label='ops_broker_imports')

            run(['docker', 'exec', 'vitrine_vps_mcp_connector', 'python', '-c',
                 'import os; print("CWD="+os.getcwd()); import connector_runtime; print("CONNECTOR_RUNTIME_IMPORT=PASS")'],
                label='connector_runtime_import')

            run([
                'docker', 'exec', 'vitrine_vps_mcp_connector',
                'python', '/app/probe_streamable_http.py',
                '--url', 'http://127.0.0.1:8765/mcp',
                '--calls', '0',
                '--sessions', '1',
                '--catalog-only',
                '--require-tool', 'project_deploy',
                '--require-tool', 'connector_health',
                '--require-tool', 'project_context',
                '--require-tool', 'project_write_file',
                '--require-tool', 'project_php_lint',
            ], label='mcp_protocol_registry')

        print('CONNECTOR_RELEASE_INSTALLED=SIM')
        return 0
    except Exception as exc:
        print(f'INSTALLATION_FAILED={exc}', file=sys.stderr, flush=True)
        restore_backup(backup)
        print('ROLLBACK_COMPLETED=SIM', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
