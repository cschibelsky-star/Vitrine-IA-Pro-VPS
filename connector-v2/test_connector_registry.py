from __future__ import annotations

import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def fail(message: str) -> None:
    raise SystemExit(f"CONNECTOR_STABILIZATION_TEST=FAIL {message}")


def test_no_nested_fastmcp() -> None:
    helper=ROOT/'main_tvsumare_tools.py'
    tree=ast.parse(helper.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and 'fastmcp' in node.module.lower():
            fail('main_tvsumare_tools importa FastMCP')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id=='FastMCP':
            fail('main_tvsumare_tools instancia FastMCP')
        if isinstance(node, ast.Attribute) and node.attr=='tool':
            fail('main_tvsumare_tools registra @mcp.tool')


def test_project_registry() -> None:
    from project_registry import get_project_context
    ctx=get_project_context('tvsumare')
    if not ctx.get('ok'): fail('tvsumare ausente do registry')
    expected={
        'root':'/srv/tvsumare',
        'repository':'/srv/tvsumare/repository',
        'compose_file':'/srv/tvsumare/repository/docker-compose.vps.yml',
        'service':'web',
        'homologation_domain':'tv-hml.vitrineiapro.com.br',
    }
    for key,value in expected.items():
        if ctx.get(key)!=value: fail(f'{key} divergente: {ctx.get(key)!r}')
    unknown=get_project_context('projeto-inexistente')
    if unknown.get('ok') is not False or unknown.get('error')!='unknown_project':
        fail('registry não rejeita projeto desconhecido de forma determinística')


def test_runtime_health() -> None:
    from connector_runtime import CONNECTOR_ID, CONNECTOR_VERSION, connector_health, project_context
    if CONNECTOR_ID!='vitrine_ops': fail(f'connector_id técnico inválido: {CONNECTOR_ID!r}')
    if not CONNECTOR_VERSION.startswith('2.1.0-stabilization'):
        fail(f'versão inesperada: {CONNECTOR_VERSION!r}')
    health=connector_health()
    required=('ok','connector_id','version','registry_version','projects')
    for key in required:
        if key not in health: fail(f'health sem campo {key}')
    if not health.get('ok'): fail('connector_health não retornou ok')
    if health.get('connector_id')!='vitrine_ops': fail('connector_health diverge do id técnico')
    ctx=project_context('tvsumare')
    if ctx.get('repository')!='/srv/tvsumare/repository': fail('project_context não usa registry canônico')


def test_installer_contract() -> None:
    text=(ROOT/'install_connector_v2.py').read_text(encoding='utf-8')
    for token in ('def ensure_after(', 'def ensure_before(', 'CONNECTOR_STABILIZATION_INSTALLED=SIM'):
        if token not in text: fail(f'instalador sem contrato idempotente: {token}')
    if 'replace_once(' in text:
        fail('instalador ainda contém patch estritamente não idempotente')


def main() -> None:
    test_no_nested_fastmcp()
    test_project_registry()
    test_runtime_health()
    test_installer_contract()
    print('CONNECTOR_STABILIZATION_TEST=PASS')


if __name__=='__main__':
    main()
