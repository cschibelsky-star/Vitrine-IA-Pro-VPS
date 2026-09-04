from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

LIVE_ROOT = Path('/srv/connectors/vitrine-vps-mcp')
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.backup-ops-api-route-v3-{STAMP}'))


def run(command: list[str], cwd: Path) -> None:
    proc = subprocess.run(command, cwd=str(cwd), text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def patch_tools(path: Path) -> None:
    backup(path)
    text = path.read_text(encoding='utf-8')

    if 'OPS_API_URL = os.getenv(' not in text:
        marker = 'OPS_BROKER_URL = os.getenv("OPS_BROKER_URL", "http://ops_broker:8770").rstrip("/")\n'
        if marker not in text:
            raise SystemExit('OPS_BROKER_URL marker not found')
        text = text.replace(
            marker,
            'OPS_API_URL = os.getenv("OPS_API_URL", "http://host.docker.internal:18080").rstrip("/")\n' + marker,
            1,
        )

    if 'OPS_API_FALLBACK = os.getenv(' not in text:
        marker = 'OPS_REQUEST_TIMEOUT = float(os.getenv("OPS_REQUEST_TIMEOUT", "1200"))\n'
        if marker not in text:
            raise SystemExit('OPS_REQUEST_TIMEOUT marker not found')
        text = text.replace(
            marker,
            marker + 'OPS_API_FALLBACK = os.getenv("OPS_API_FALLBACK", "1").strip().lower() not in {"0", "false", "no", "off"}\n',
            1,
        )

    if 'transport_url' not in text or 'ops_broker_fallback' not in text:
        start = text.find('def _request(')
        if start == -1:
            raise SystemExit('_request function not found')
        next_def = re.search(r'\n\ndef [A-Za-z_][A-Za-z0-9_]*\(', text[start + 1:])
        if next_def is None:
            raise SystemExit('next function after _request not found')
        end = start + 1 + next_def.start()

        replacement = '''def _decode(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:2000]}
    if response.status_code >= 400:
        return {"ok": False, "status_code": response.status_code, "body": body}
    return body


def _request_once(base_url: str, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {OPS_BROKER_TOKEN}"}
    with httpx.Client(timeout=OPS_REQUEST_TIMEOUT) as client:
        response = client.request(method, f"{base_url}{path}", headers=headers, json=payload)
    return _decode(response)


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        result = _request_once(OPS_API_URL, method, path, payload)
        result.setdefault("transport", "ops_api")
        result.setdefault("transport_url", OPS_API_URL)
        return result
    except (httpx.HTTPError, OSError) as exc:
        if not OPS_API_FALLBACK:
            return {"ok": False, "transport": "ops_api", "transport_url": OPS_API_URL, "error": "ops_api_unreachable", "detail": type(exc).__name__}

    try:
        result = _request_once(OPS_BROKER_URL, method, path, payload)
        result.setdefault("transport", "ops_broker_fallback")
        result.setdefault("transport_url", OPS_BROKER_URL)
        return result
    except (httpx.HTTPError, OSError) as exc:
        return {"ok": False, "transport": "ops_broker_fallback", "transport_url": OPS_BROKER_URL, "error": "ops_api_and_broker_unreachable", "detail": type(exc).__name__}
'''
        text = text[:start] + replacement + text[end:]

    path.write_text(text, encoding='utf-8')


def patch_compose(path: Path) -> None:
    backup(path)
    text = path.read_text(encoding='utf-8')
    service_marker = '  vps_mcp_connector:\n'
    if service_marker not in text:
        raise SystemExit('vps_mcp_connector service not found')
    service_start = text.index(service_marker)
    tail = text[service_start:]

    if 'OPS_API_URL:' not in tail:
        marker = '      OPS_BROKER_URL: http://ops_broker:8770\n'
        if marker not in tail:
            raise SystemExit('OPS_BROKER_URL compose marker not found')
        absolute = service_start + tail.index(marker)
        insert_at = absolute + len(marker)
        text = text[:insert_at] + '      OPS_API_URL: http://host.docker.internal:18080\n      OPS_API_FALLBACK: "1"\n' + text[insert_at:]
        tail = text[service_start:]

    host_entry = '      - "host.docker.internal:host-gateway"\n'
    if host_entry not in tail:
        env_marker = '    environment:\n'
        relative = tail.find(env_marker)
        if relative == -1:
            raise SystemExit('vps_mcp_connector environment block not found')
        insert_at = service_start + relative
        text = text[:insert_at] + '    extra_hosts:\n' + host_entry + text[insert_at:]

    path.write_text(text, encoding='utf-8')


def main() -> None:
    tools = LIVE_ROOT / 'project_manager_tools.py'
    compose = LIVE_ROOT / 'docker-compose.mcp.yml'
    main_py = LIVE_ROOT / 'main.py'

    for required in (tools, compose, main_py):
        if not required.is_file():
            raise SystemExit(f'Required file not found: {required}')

    patch_tools(tools)
    patch_compose(compose)

    # Syntax only on host: no third-party imports required.
    run(['python3', '-m', 'py_compile', 'project_manager_tools.py', 'main.py'], LIVE_ROOT)
    run(['docker', 'compose', '-f', 'docker-compose.mcp.yml', 'config', '-q'], LIVE_ROOT)

    # Build image without replacing the currently running MCP.
    run(['docker', 'compose', '-f', 'docker-compose.mcp.yml', 'build', 'vps_mcp_connector'], LIVE_ROOT)

    # Runtime/import compatibility is validated inside the freshly built image,
    # where httpx/FastMCP and all production dependencies are installed.
    run([
        'docker', 'compose', '-f', 'docker-compose.mcp.yml', 'run', '--rm', '--no-deps',
        '--entrypoint', 'python', 'vps_mcp_connector', '-c',
        'import project_manager_tools; import main; '
        'assert hasattr(project_manager_tools, "project_read_file"); '
        'assert hasattr(project_manager_tools, "project_manifest_create"); '
        'print("IMPORT_COMPATIBILITY_DOCKER=OK")'
    ], LIVE_ROOT)

    # Only after successful image validation do we cut over the live connector.
    run(['docker', 'compose', '-f', 'docker-compose.mcp.yml', 'up', '-d', '--no-deps', 'vps_mcp_connector'], LIVE_ROOT)

    print('MCP_OPS_API_ROUTE_V3_INSTALLED=SIM')
    print(f'BACKUP_STAMP={STAMP}')
    print('STRATEGY=in_place_transport_patch_with_docker_preflight')
    print('OPS_API_URL=http://host.docker.internal:18080')
    print('OPS_API_FALLBACK=1')


if __name__ == '__main__':
    main()
