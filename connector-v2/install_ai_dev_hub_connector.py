from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
SOURCE = Path(__file__).resolve().parent
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.backup-ai-dev-hub-{STAMP}'))


def insert_before(text: str, marker: str, block: str, sentinel: str, label: str) -> str:
    if sentinel in text:
        return text
    if marker not in text:
        raise RuntimeError(f'{label}: marcador não encontrado')
    return text.replace(marker, block + marker, 1)


def ensure_compose_env(text: str, service: str, entry: str) -> str:
    service_marker = f'  {service}:\n'
    if service_marker not in text:
        raise RuntimeError(f'Compose: serviço {service} não encontrado')

    service_start = text.index(service_marker)
    next_service = text.find('\n  ', service_start + len(service_marker))
    service_end = len(text) if next_service == -1 else next_service
    block = text[service_start:service_end]

    if entry in block:
        return text

    env_marker = '    environment:\n'
    env_pos = block.find(env_marker)
    if env_pos == -1:
        insertion = service_marker + '    environment:\n' + f'      {entry}\n'
        return text.replace(service_marker, insertion, 1)

    absolute = service_start + env_pos + len(env_marker)
    return text[:absolute] + f'      {entry}\n' + text[absolute:]


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f'Raiz do conector não encontrada: {ROOT}')

    source_tools = SOURCE / 'ai_dev_hub_tools.py'
    if not source_tools.exists():
        raise RuntimeError(f'Arquivo fonte ausente: {source_tools}')

    target_tools = ROOT / 'ai_dev_hub_tools.py'
    backup(target_tools)
    shutil.copy2(source_tools, target_tools)

    main_py = ROOT / 'main.py'
    if not main_py.exists():
        raise RuntimeError(f'MCP main.py não encontrado: {main_py}')

    backup(main_py)
    text = main_py.read_text(encoding='utf-8')

    import_block = '''\nfrom ai_dev_hub_tools import (\n    ai_dev_chat as _ai_dev_chat,\n    ai_dev_compare as _ai_dev_compare,\n    ai_dev_code_review as _ai_dev_code_review,\n    ai_dev_models as _ai_dev_models,\n    ai_dev_usage as _ai_dev_usage,\n)\n'''

    if 'from ai_dev_hub_tools import' not in text:
        marker = 'from typing import Any\n'
        if marker not in text:
            raise RuntimeError('main.py: import typing.Any não encontrado')
        text = text.replace(marker, marker + import_block, 1)

    tools_block = '''\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef ai_dev_chat(\n    project_id: str,\n    prompt: str,\n    profile: str = "balanced",\n    model: str = "",\n    provider: str = "roteia",\n    system: str = "",\n) -> dict[str, Any]:\n    return _ai_dev_chat(project_id, prompt, profile, model, provider, system)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef ai_dev_compare(\n    project_id: str,\n    prompt: str,\n    models: list[str] | None = None,\n    provider: str = "roteia",\n    system: str = "",\n) -> dict[str, Any]:\n    return _ai_dev_compare(project_id, prompt, models, provider, system)\n\n\n@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})\ndef ai_dev_code_review(\n    project_id: str,\n    prompt: str,\n    profile: str = "balanced",\n    model: str = "",\n    provider: str = "roteia",\n) -> dict[str, Any]:\n    return _ai_dev_code_review(project_id, prompt, profile, model, provider)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef ai_dev_models(\n    provider: str = "roteia",\n    tier: str = "",\n    modality: str = "text",\n) -> dict[str, Any]:\n    return _ai_dev_models(provider, tier, modality)\n\n\n@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})\ndef ai_dev_usage(project_id: str = "vitrine-ia-pro-core") -> dict[str, Any]:\n    return _ai_dev_usage(project_id)\n'''

    text = insert_before(
        text,
        '\nif __name__ == "__main__":\n',
        tools_block,
        'def ai_dev_chat(',
        'registro AI Dev Hub MCP tools',
    )
    main_py.write_text(text, encoding='utf-8')

    dockerfile = ROOT / 'Dockerfile'
    if dockerfile.exists():
        backup(dockerfile)
        docker_text = dockerfile.read_text(encoding='utf-8')
        copy_line = next(
            (line for line in docker_text.splitlines() if line.startswith('COPY ') and line.endswith(' ./')),
            None,
        )
        if copy_line and 'ai_dev_hub_tools.py' not in copy_line.split():
            updated = copy_line[:-3] + ' ai_dev_hub_tools.py ./'
            docker_text = docker_text.replace(copy_line, updated, 1)
            dockerfile.write_text(docker_text, encoding='utf-8')

    compose = ROOT / 'docker-compose.connector-v2.override.yml'
    if not compose.exists():
        template = SOURCE / 'docker-compose.connector-v2.override.yml'
        if not template.exists():
            raise RuntimeError('Compose override do conector não encontrado')
        shutil.copy2(template, compose)

    backup(compose)
    compose_text = compose.read_text(encoding='utf-8')
    compose_text = ensure_compose_env(
        compose_text,
        'vps_mcp_connector',
        'AI_DEV_HUB_BASE_URL: ${AI_DEV_HUB_BASE_URL}',
    )
    compose_text = ensure_compose_env(
        compose_text,
        'vps_mcp_connector',
        'AI_DEV_HUB_INTERNAL_TOKEN: ${AI_DEV_HUB_INTERNAL_TOKEN}',
    )
    compose.write_text(compose_text, encoding='utf-8')

    print('AI_DEV_HUB_CONNECTOR_INSTALLED')
    print(f'BACKUP_STAMP={STAMP}')
    print('NEXT: configure AI_DEV_HUB_BASE_URL and AI_DEV_HUB_INTERNAL_TOKEN, then rebuild connector')


if __name__ == '__main__':
    main()
