from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path('/srv/tvsumare/repository')
DOCKERFILE = REPO / 'Dockerfile'
CHAIN = [
    'docker/apply-radar-editorial-policy.php',
    'docker/apply-video-ai-hardening.php',
    'docker/apply-boletim-diversity-hardening.php',
    'docker/apply-social-distribution-hardening.php',
    'docker/apply-admin-module-hardening.php',
    'docker/apply-reporter-queue-hardening.php',
    'docker/apply-heygen-recovery.php',
    'docker/apply-boletim-auto-presenter-ux.php',
    'docker/apply-reporter-humanization.php',
    'docker/apply-presenter-catalog-integration.php',
    'docker/apply-heygen-credit-revalidation.php',
    'docker/apply-reporter-dedup-hardening.php',
    'docker/apply-heygen-v3-schema-fix.php',
    'docker/apply-video-branding.php',
    'docker/apply-youtube-publishing-integration.php',
    'docker/test-reporter-dedup.php',
    'docker/test-youtube-integration.php',
    'docker/run-homologation-smoke.php',
]


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout)


def main() -> None:
    if not REPO.is_dir():
        raise SystemExit(f'REPO_NOT_FOUND={REPO}')
    if not DOCKERFILE.is_file():
        raise SystemExit(f'DOCKERFILE_NOT_FOUND={DOCKERFILE}')

    print('TVSUMARE_BUILD_CHAIN_AUDIT=START')
    print(f'REPO={REPO}')

    git = run(['git', 'status', '--short', '--branch'], REPO)
    print('--- GIT STATUS ---')
    print(git.stdout.rstrip())

    missing = [rel for rel in CHAIN if not (REPO / rel).is_file()]
    print('--- CHAIN FILE CHECK ---')
    if missing:
        for rel in missing:
            print(f'MISSING={rel}')
    else:
        print('ALL_CHAIN_FILES_PRESENT=YES')

    with tempfile.TemporaryDirectory(prefix='tvsumare-build-audit-') as td:
        work = Path(td) / 'repository'
        shutil.copytree(REPO, work, symlinks=True, ignore=shutil.ignore_patterns('.git'))

        report: list[dict[str, object]] = []
        for index, rel in enumerate(CHAIN, start=1):
            target = work / rel
            if not target.is_file():
                report.append({'step': index, 'file': rel, 'ok': False, 'exit_code': 127, 'output': 'file_missing'})
                continue

            proc = run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m', '-v', f'{work}:/var/www/html:rw', '--entrypoint', 'php', 'php:8.3-cli', f'/var/www/html/{rel}'], timeout=300)
            output = ((proc.stdout or '') + (proc.stderr or '')).strip()
            report.append({'step': index, 'file': rel, 'ok': proc.returncode == 0, 'exit_code': proc.returncode, 'output': output[-4000:]})
            status = 'PASS' if proc.returncode == 0 else 'FAIL'
            print(f'[{index:02d}] {status} {rel} exit={proc.returncode}')
            if output:
                print(output[-1200:])

        print('--- SUMMARY JSON ---')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        failed = [item for item in report if not item['ok']]
        print(f'FAILED_STEPS={len(failed)}')
        for item in failed:
            print(f"FAIL step={item['step']} file={item['file']} exit={item['exit_code']}")

    print('TVSUMARE_BUILD_CHAIN_AUDIT=END')


if __name__ == '__main__':
    main()
