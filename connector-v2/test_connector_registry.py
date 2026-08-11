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


def main() -> None:
    test_no_nested_fastmcp()
    test_project_registry()
    print('CONNECTOR_STABILIZATION_TEST=PASS')


if __name__=='__main__':
    main()
