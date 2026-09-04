from __future__ import annotations

import json
import subprocess
from datetime import datetime

CONTAINER = 'tvsumare_web'


def run(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, text=True, capture_output=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def section(title: str) -> None:
    print(f'\n=== {title} ===')


def docker_exec(*args: str) -> tuple[int, str, str]:
    return run(['docker', 'exec', CONTAINER, *args])


def check_marker(path: str, marker: str, label: str) -> bool:
    code, out, err = docker_exec('sh', '-lc', f"grep -Fq {json.dumps(marker)} {json.dumps(path)}")
    ok = code == 0
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    if err:
        print(err)
    return ok


def main() -> None:
    print('TVSUMARE_RUNTIME_AUDIT=START')
    print('AT=' + datetime.now().isoformat(timespec='seconds'))

    section('CONTAINER')
    code, out, err = run(['docker', 'inspect', CONTAINER, '--format', 'STATUS={{.State.Status}} HEALTH={{if .State.Health}}{{.State.Health.Status}}{{end}} IMAGE={{.Config.Image}}'])
    print(out or err)
    if code != 0:
        raise SystemExit(2)

    section('HEALTH INTERNO')
    code, out, err = docker_exec('curl', '-fsS', 'http://127.0.0.1/health.php')
    print(out or err)

    section('PHP LINT RUNTIME')
    files = [
        '/var/www/html/admin/_menu.php',
        '/var/www/html/admin/radar-regional.php',
        '/var/www/html/admin/nova-noticia.php',
        '/var/www/html/admin/drafts.php',
        '/var/www/html/admin/boletim-ia.php',
        '/var/www/html/admin/reporter-ia.php',
        '/var/www/html/admin/distribuicao-social.php',
        '/var/www/html/admin/tvplay.php',
        '/var/www/html/includes/youtube_oauth.php',
    ]
    lint_fail = 0
    for path in files:
        code, out, err = docker_exec('php', '-l', path)
        ok = code == 0
        print(f"{'PASS' if ok else 'FAIL'} {path}: {out or err}")
        if not ok:
            lint_fail += 1

    section('MARCADORES RUNTIME')
    checks = [
        ('/var/www/html/admin/reporter-ia.php', 'function rpia_job_state(', 'Reporter maquina de estados'),
        ('/var/www/html/admin/reporter-ia.php', "send_lock_at", 'Reporter trava envio duplicado'),
        ('/var/www/html/admin/reporter-ia.php', "roteiro_aprovado", 'Reporter exige aprovacao'),
        ('/var/www/html/admin/reporter-ia.php', 'function rpia_job_dedupe_key(', 'Reporter dedupe'),
        ('/var/www/html/admin/distribuicao-social.php', 'function ds_queue_active(', 'Social fila operacional'),
        ('/var/www/html/admin/distribuicao-social.php', 'ds_generate_copy', 'Social legenda automatica'),
        ('/var/www/html/admin/distribuicao-social.php', 'network_status', 'Social status por plataforma'),
        ('/var/www/html/admin/boletim-ia.php', 'bia_pick_distinct', 'Boletim selecao distinta'),
        ('/var/www/html/admin/_menu.php', 'apresentadores-ia.php', 'Sidebar apresentadores IA'),
        ('/var/www/html/admin/tvplay.php', 'youtube', 'TV Play integracao YouTube'),
    ]
    marker_fail = sum(0 if check_marker(*item) else 1 for item in checks)

    section('HTTP ADMIN SEM CREDENCIAIS')
    for uri in ['/admin/', '/admin/reporter-ia.php', '/admin/boletim-ia.php', '/admin/distribuicao-social.php', '/admin/tvplay.php']:
        code, out, err = docker_exec('sh', '-lc', f"curl -sS -o /dev/null -w '%{{http_code}} %{{redirect_url}}' http://127.0.0.1{uri}")
        print(f'{uri} -> {out or err}')

    section('LOGS RECENTES APACHE/PHP')
    commands = [
        "tail -n 120 /var/log/apache2/error.log 2>/dev/null || true",
        "find /var/www/html/logs -maxdepth 1 -type f -mmin -180 -print 2>/dev/null | sort | tail -n 20",
    ]
    for cmd in commands:
        code, out, err = docker_exec('sh', '-lc', cmd)
        if out:
            print(out)
        if err:
            print(err)

    section('DADOS E PERMISSOES')
    code, out, err = docker_exec('sh', '-lc', "for d in data uploads videos logs; do printf '%s ' \"$d\"; test -r /var/www/html/$d && printf 'R' || printf '-'; test -w /var/www/html/$d && printf 'W' || printf '-'; printf '\n'; done")
    print(out or err)

    section('RESUMO')
    total_fail = lint_fail + marker_fail
    print(f'RUNTIME_LINT_FAIL={lint_fail}')
    print(f'RUNTIME_MARKER_FAIL={marker_fail}')
    print(f'RUNTIME_STRUCTURAL_FAIL={total_fail}')
    print('TVSUMARE_RUNTIME_AUDIT=END')


if __name__ == '__main__':
    main()
