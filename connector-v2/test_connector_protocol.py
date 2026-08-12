from __future__ import annotations

import argparse
import ast
import asyncio
import json
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

HERE = Path(__file__).resolve().parent
SECRET_SENTINEL = "TEST_SECRET_MUST_NOT_APPEAR"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _BrokerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/tvsumare/health":
            self.send_error(404)
            return
        payload = json.dumps({"ok": True, "service": "tvsumare"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: Any) -> None:
        return


def serve(port: int, broker_port: int, manifest_root: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    os.environ["PROJECT_MANIFEST_ROOT"] = str(manifest_root)
    os.environ["OPS_BROKER_URL"] = f"http://127.0.0.1:{broker_port}"
    os.environ["OPS_BROKER_TOKEN"] = SECRET_SENTINEL
    sys.path.insert(0, str(HERE))

    from connector_observability import SafeToolCallLoggingMiddleware
    from connector_runtime import connector_health as runtime_health
    from connector_runtime import project_context as runtime_context
    from fastmcp import FastMCP
    from main_tvsumare_tools import tvsumare_health as runtime_tvsumare_health

    broker = ThreadingHTTPServer(("127.0.0.1", broker_port), _BrokerHandler)
    threading.Thread(target=broker.serve_forever, daemon=True).start()

    mcp = FastMCP("Vitrine Connector Protocol Test")
    mcp.add_middleware(SafeToolCallLoggingMiddleware())

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def system_health() -> dict[str, Any]:
        return {"ok": True, "checked_at": "2026-08-12T00:00:00+00:00"}

    @mcp.tool
    def instrumentation_error_probe() -> dict[str, Any]:
        raise ValueError("synthetic-test-error")

    mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})(runtime_health)
    mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})(runtime_context)
    mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})(runtime_tvsumare_health)
    mcp.run(transport="http", host="127.0.0.1", port=port, show_banner=False)


def _serializable(result: Any) -> bool:
    json.dumps(result.model_dump(mode="json", by_alias=True, exclude_none=True))
    return True


def _helper_has_registry() -> bool:
    tree = ast.parse((HERE / "main_tvsumare_tools.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and "fastmcp" in ast.unparse(node).lower():
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any("mcp.tool" in ast.unparse(decorator) for decorator in node.decorator_list):
                return True
    return False


async def _single_session_call(url: str) -> tuple[str | None, bool]:
    async with httpx.AsyncClient(timeout=10) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("system_health")
                return session_id(), not result.isError


async def run_protocol_checks(url: str) -> list[str]:
    gates: list[str] = []
    async with httpx.AsyncClient(timeout=10) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = [tool.name for tool in listed.tools]
                required = {"system_health", "connector_health", "project_context", "tvsumare_health"}
                assert required <= set(names)
                gates.append("DISCOVERY_PASS")
                assert len(names) == len(set(names))
                assert not _helper_has_registry()
                gates.append("NO_DUPLICATE_REGISTRY_PASS")

                health = await session.call_tool("system_health")
                assert not health.isError and bool(session_id())
                gates.append("CALL_SYSTEM_HEALTH_PASS")
                assert _serializable(health)
                gates.append("SERIALIZATION_PASS")
                for _ in range(9):
                    repeated = await session.call_tool("system_health")
                    assert not repeated.isError and _serializable(repeated)
                gates.append("SAME_SESSION_10_CALLS_PASS")

                context = await session.call_tool("project_context", {"project_id": "tvsumare"})
                assert not context.isError
                assert context.structuredContent["ok"] is True
                assert context.structuredContent["repository_root"] == "/srv/tvsumare/repository"
                gates.append("PROJECT_CONTEXT_PASS")

                tvsumare = await session.call_tool("tvsumare_health")
                assert not tvsumare.isError and tvsumare.structuredContent["ok"] is True
                gates.append("TVSUMARE_HEALTH_PASS")

                expected_error = await session.call_tool("instrumentation_error_probe")
                assert expected_error.isError

    sessions = await asyncio.gather(_single_session_call(url), _single_session_call(url))
    ids = [item[0] for item in sessions]
    assert ids[0] and ids[1] and ids[0] != ids[1]
    assert all(item[1] for item in sessions)
    gates.append("MULTI_SESSION_PASS")
    return gates


def wait_until_ready(port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("test server exited before becoming ready")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("test server did not start")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--broker-port", type=int)
    parser.add_argument("--manifest-root", type=Path)
    args = parser.parse_args()
    if args.serve:
        serve(args.port, args.broker_port, args.manifest_root)
        return

    with tempfile.TemporaryDirectory(prefix="connector-protocol-") as temp:
        manifest_root = Path(temp)
        manifest = json.loads((HERE.parent / "project-manager" / "manifests" / "tvsumare.json").read_text(encoding="utf-8"))
        (manifest_root / "tvsumare.json").write_text(json.dumps(manifest), encoding="utf-8")
        port, broker_port = _free_port(), _free_port()
        log_path = manifest_root / "server.log"
        log_handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", "--port", str(port), "--broker-port", str(broker_port), "--manifest-root", str(manifest_root)],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_until_ready(port, process)
            gates = asyncio.run(run_protocol_checks(f"http://127.0.0.1:{port}/mcp"))
        finally:
            process.terminate()
            process.wait(timeout=10)
            log_handle.close()
        output = log_path.read_text(encoding="utf-8")
        assert SECRET_SENTINEL not in output
        assert re.search(r"TOOL_CALL name=system_health request_id=\S+", output)
        assert re.search(
            r"TOOL_RESULT name=system_health result_type=ToolResult serialized_size=\d+ duration_ms=\d+",
            output,
        )
        assert "TOOL_ERROR name=instrumentation_error_probe exception=ToolError" in output
        for gate in gates:
            print(gate)
        print("SAFE_INSTRUMENTATION_PASS")


if __name__ == "__main__":
    main()
