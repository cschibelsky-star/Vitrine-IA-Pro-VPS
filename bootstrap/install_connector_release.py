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


def run(command: list[str], cwd: Path | None = None) -> None:
    print('+', ' '.join(command), flush=True)
    subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)


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
    failed = CONNECTOR_ROOT.with_name(CONNECTOR_ROOT.name + '.failed')
    if failed.exists():
        shutil.rmtree(failed)
    if CONNECTOR_ROOT.exists():
        CONNECTOR_ROOT.rename(failed)
    shutil.copytree(backup, CONNECTOR_ROOT, symlinks=True)
    run(compose_command('build', '--no-cache'), CONNECTOR_ROOT)
    run(compose_command('up', '-d'), CONNECTOR_ROOT)


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
            run(['git', 'clone', '--depth', '1', '--branch', args.branch, args.repository, str(checkout)])

            # Testa a fonte antes de tocar no runtime instalado.
            run([sys.executable, str(checkout / 'connector-v2' / 'test_connector_stabilization.py')], checkout)
            run([sys.executable, '-m', 'py_compile',
                 str(checkout / 'connector-v2' / 'main_tvsumare_tools.py'),
                 str(checkout / 'connector-v2' / 'connector_runtime.py'),
                 str(checkout / 'project-manager' / 'project_deployment_engine.py')])

            run([sys.executable, str(checkout / 'connector-v2' / 'install_connector_v2.py')])
            run([sys.executable, str(checkout / 'project-manager' / 'install_project_manager.py')])

            run([
                sys.executable,
                '-m',
                'py_compile',
                str(CONNECTOR_ROOT / 'ops_broker.py'),
                str(CONNECTOR_ROOT / 'main.py'),
                str(CONNECTOR_ROOT / 'tvsumare_operations.py'),
                str(CONNECTOR_ROOT / 'tvsumare_tools.py'),
                str(CONNECTOR_ROOT / 'project_manager_operations.py'),
                str(CONNECTOR_ROOT / 'project_manager_tools.py'),
                str(CONNECTOR_ROOT / 'project_deployment_engine.py'),
            ])

            run(compose_command('config'), CONNECTOR_ROOT)
            run(compose_command('build', '--no-cache'), CONNECTOR_ROOT)
            run(compose_command('up', '-d'), CONNECTOR_ROOT)
            run(compose_command('ps', '-a'), CONNECTOR_ROOT)

            run(['docker', 'exec', 'vitrine_mcp_ops_broker', 'python', '-c', 'import project_deployment_engine, project_manager_operations, tvsumare_operations'])
            run(['docker', 'exec', 'vitrine_vps_mcp_connector', 'python', '-c', 'import main; assert hasattr(main, "project_deploy")'])

        print('CONNECTOR_RELEASE_INSTALLED=SIM')
        return 0
    except Exception as exc:
        print(f'INSTALLATION_FAILED={exc}', file=sys.stderr, flush=True)
        restore_backup(backup)
        print('ROLLBACK_COMPLETED=SIM', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
