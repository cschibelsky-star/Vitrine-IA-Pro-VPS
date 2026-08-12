from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _load_bearer(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'Bearer\s+([^"\s;]+)', text)
    if not match:
        raise RuntimeError("Bearer token not found in nginx configuration")
    return match.group(1)


def _result_summary(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    content = getattr(result, "content", [])
    dumped = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    encoded = json.dumps(dumped, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {
        "is_error": bool(getattr(result, "isError", False)),
        "content_types": [getattr(item, "type", type(item).__name__) for item in content],
        "has_structured_content": structured is not None,
        "structured_type": type(structured).__name__ if structured is not None else None,
        "serialized_size": len(encoded),
        "json_serializable": True,
    }


async def probe(
    url: str,
    token: str | None,
    calls: int,
    label: str,
    required_tools: set[str],
    catalog_only: bool,
) -> str | None:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with httpx.AsyncClient(headers=headers, timeout=30) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, get_session_id):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                print(f"{label}_INITIALIZE=" + initialized.serverInfo.name)
                print(f"{label}_SESSION_ID_PRESENT=" + str(bool(get_session_id())))
                listed = await session.list_tools()
                names = [tool.name for tool in listed.tools]
                tool_payloads = [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in listed.tools]
                json.dumps(tool_payloads, ensure_ascii=False)
                invalid_input = [
                    tool.name
                    for tool in listed.tools
                    if not isinstance(tool.inputSchema, dict) or tool.inputSchema.get("type") != "object"
                ]
                invalid_output = [
                    tool.name
                    for tool in listed.tools
                    if getattr(tool, "outputSchema", None) is not None
                    and (
                        not isinstance(tool.outputSchema, dict)
                        or tool.outputSchema.get("type") != "object"
                    )
                ]
                print(f"{label}_TOOLS_COUNT=" + str(len(names)))
                print(f"{label}_SYSTEM_HEALTH_DISCOVERED=" + str("system_health" in names))
                print(f"{label}_CONNECTOR_HEALTH_DISCOVERED=" + str("connector_health" in names))
                print(f"{label}_PROJECT_CONTEXT_DISCOVERED=" + str("project_context" in names))
                print(f"{label}_TVSUMARE_HEALTH_DISCOVERED=" + str("tvsumare_health" in names))
                print(f"{label}_DUPLICATE_TOOL_NAMES=" + json.dumps(sorted({n for n in names if names.count(n) > 1})))
                print(f"{label}_SCHEMAS_JSON_SERIALIZABLE=True")
                print(f"{label}_INVALID_INPUT_SCHEMAS=" + json.dumps(invalid_input))
                print(f"{label}_INVALID_OUTPUT_SCHEMAS=" + json.dumps(invalid_output))
                missing = sorted(required_tools - set(names))
                duplicates = sorted({name for name in names if names.count(name) > 1})
                if missing:
                    raise RuntimeError("required_tools_missing:" + ",".join(missing))
                if duplicates:
                    raise RuntimeError("duplicate_tool_names:" + ",".join(duplicates))
                if invalid_input or invalid_output:
                    raise RuntimeError(
                        "invalid_tool_schemas:input="
                        + ",".join(invalid_input)
                        + ";output="
                        + ",".join(invalid_output)
                    )
                if catalog_only:
                    print(f"{label}_CATALOG_VALID=True")
                    return get_session_id()
                for index in range(calls):
                    result = await session.call_tool("system_health")
                    print(f"{label}_SYSTEM_HEALTH_{index + 1}=" + json.dumps(_result_summary(result), sort_keys=True))
                if "tvsumare_health" in names:
                    result = await session.call_tool("tvsumare_health")
                    print(f"{label}_TVSUMARE_HEALTH=" + json.dumps(_result_summary(result), sort_keys=True))
                if "project_context" in names:
                    result = await session.call_tool("project_context", {"project_id": "tvsumare"})
                    print(f"{label}_PROJECT_CONTEXT=" + json.dumps(_result_summary(result), sort_keys=True))
                return get_session_id()


async def run_probes(
    url: str,
    token: str | None,
    calls: int,
    sessions: int,
    required_tools: set[str],
    catalog_only: bool,
) -> None:
    ids = await asyncio.gather(
        *(
            probe(
                url,
                token,
                calls if index == 0 else 1,
                f"SESSION_{index + 1}",
                required_tools,
                catalog_only,
            )
            for index in range(sessions)
        )
    )
    present = [session_id for session_id in ids if session_id]
    print("MULTI_SESSION_IDS_UNIQUE=" + str(len(present) == sessions and len(set(present)) == sessions))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--calls", type=int, default=1)
    parser.add_argument("--sessions", type=int, default=1)
    parser.add_argument("--require-tool", action="append", default=[])
    parser.add_argument("--catalog-only", action="store_true")
    args = parser.parse_args()
    token = _load_bearer(args.token_file) if args.token_file else None
    asyncio.run(
        run_probes(
            args.url,
            token,
            args.calls,
            args.sessions,
            set(args.require_tool),
            args.catalog_only,
        )
    )


if __name__ == "__main__":
    main()
