from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path

DEFAULT_PATH = Path('/srv/connectors/vitrine-vps-mcp/docker-compose.connector-v2.override.yml')
EXPECTED = {
    'PROJECT_MANIFEST_ROOT': '/app/project-manifests',
    'PROJECT_WORKSPACE_ROOTS': '/srv/tvsumare,/srv/projects',
    'OPS_AUDIT_LOG': '/var/log/vitrine-ops/audit.jsonl',
}


def repair_environment_keys(text: str, service: str, expected: dict[str, str]) -> str:
    service_re = re.compile(rf'(?ms)^  {re.escape(service)}:\s*\n(?P<body>.*?)(?=^  [A-Za-z0-9_.-]+:\s*$|^[A-Za-z0-9_.-]+:\s*$|\Z)')
    match = service_re.search(text)
    if match is None:
        raise RuntimeError(f'service_not_found:{service}')

    body = match.group('body')
    env_re = re.compile(r'(?ms)^    environment:\s*\n(?P<env>.*?)(?=^    [A-Za-z0-9_.-]+:\s*$|\Z)')
    env_match = env_re.search(body)
    if env_match is None:
        insertion = '    environment:\n' + ''.join(f'      {key}: {value}\n' for key, value in expected.items())
        new_body = insertion + body
    else:
        env = env_match.group('env')
        lines = env.splitlines()
        key_re = re.compile(r'^\s{6}([A-Za-z_][A-Za-z0-9_]*):')
        seen: set[str] = set()
        kept: list[str] = []
        for line in lines:
            key_match = key_re.match(line)
            if key_match and key_match.group(1) in expected:
                key = key_match.group(1)
                if key in seen:
                    continue
                kept.append(f'      {key}: {expected[key]}')
                seen.add(key)
            else:
                kept.append(line)
        for key, value in expected.items():
            if key not in seen:
                kept.append(f'      {key}: {value}')
        new_env = '\n'.join(kept).rstrip() + '\n'
        new_body = body[:env_match.start('env')] + new_env + body[env_match.end('env'):]

    return text[:match.start('body')] + new_body + text[match.end('body'):]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', default=str(DEFAULT_PATH))
    parser.add_argument('--confirm', required=True)
    args = parser.parse_args()
    if args.confirm != 'EXECUTAR':
        raise SystemExit('confirmation_required')

    path = Path(args.path)
    if not path.is_file():
        raise SystemExit(f'override_not_found:{path}')

    original = path.read_text(encoding='utf-8')
    repaired = repair_environment_keys(original, 'ops_broker', EXPECTED)

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = path.with_name(f'{path.name}.backup-env-repair-{stamp}')
    shutil.copy2(path, backup)
    path.write_text(repaired, encoding='utf-8')

    print(f'BACKUP={backup}')
    print('CONNECTOR_OVERRIDE_ENV_REPAIRED=SIM')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
