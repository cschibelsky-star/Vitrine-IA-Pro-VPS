"""Manual acceptance of ai_work_delegate: ONE real, paid call through the MCP protocol.

Never run by the release gate. It refuses to start without --confirm EXECUTAR, checks
ai_work_delegate_status first and aborts if the ledger or Roteia configuration is not
ready, then performs a single call with a small per-call cap. The experiment id is
consumed by the ledger, so re-running with the same id is blocked (no duplicate charge).

Run it like the release probe, from a one-shot container on the MCP network:
  python /app/acceptance_ai_work_delegate.py --url http://vps_mcp_connector:8765/mcp \
      --experiment-id hml-acceptance-001 --max-charge-cents 100 --confirm EXECUTAR
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

DEFAULT_PROMPT = "Responda apenas com a palavra: OK"


async def run(url: str, experiment_id: str, prompt: str, max_charge_cents: int) -> dict[str, Any]:
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from probe_streamable_http import tool_payload

    async with httpx.AsyncClient(timeout=180) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, _session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                missing = {"ai_work_delegate", "ai_work_delegate_status"} - names
                if missing:
                    return {"ok": False, "error": "tools_missing:" + ",".join(sorted(missing))}
                status = tool_payload(await session.call_tool("ai_work_delegate_status"))
                if status.get("ready_for_paid_call") is not True:
                    return {"ok": False, "error": "not_ready_for_paid_call", "status": status}
                result = await session.call_tool(
                    "ai_work_delegate",
                    {
                        "experiment_id": experiment_id,
                        "prompt": prompt,
                        "max_charge_cents": max_charge_cents,
                        "confirm": "EXECUTAR",
                    },
                )
                payload = tool_payload(result)
                payload["ledger_after"] = tool_payload(await session.call_tool("ai_work_delegate_status")).get("ledger")
                return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--max-charge-cents", type=int, default=100)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.confirm != "EXECUTAR":
        print("ACCEPTANCE_ABORTED=confirmation_required (use --confirm EXECUTAR)", file=sys.stderr)
        return 2
    result = asyncio.run(run(args.url, args.experiment_id, args.prompt, args.max_charge_cents))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
