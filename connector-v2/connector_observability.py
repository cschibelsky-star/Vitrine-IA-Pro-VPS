from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext

LOGGER = logging.getLogger("vitrine.mcp.tools")


def _safe_identifier(value: Any, fallback: str) -> str:
    text = str(value) if value is not None else fallback
    sanitized = "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in text)
    return (sanitized or fallback)[:128]


def _request_id(context: MiddlewareContext[Any]) -> str:
    fastmcp_context = context.fastmcp_context
    value = getattr(fastmcp_context, "request_id", None) if fastmcp_context else None
    return _safe_identifier(value, "unknown")


def _json_default(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", by_alias=True, exclude_none=True)
    raise TypeError(f"not_json_serializable:{type(value).__name__}")


def serialized_size(result: Any) -> int:
    payload = {
        "content": getattr(result, "content", None),
        "structuredContent": getattr(result, "structured_content", None),
        "_meta": getattr(result, "meta", None),
    }
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")
    )


class SafeToolCallLoggingMiddleware(Middleware):
    """Logs tool lifecycle metadata without arguments, results, or secrets."""

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next):
        name = _safe_identifier(getattr(context.message, "name", None), "unknown")
        request_id = _request_id(context)
        started = time.perf_counter()
        LOGGER.info("TOOL_CALL name=%s request_id=%s", name, request_id)
        try:
            result = await call_next(context)
            size = serialized_size(result)
        except Exception as exc:
            LOGGER.error("TOOL_ERROR name=%s exception=%s", name, type(exc).__name__)
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        LOGGER.info(
            "TOOL_RESULT name=%s result_type=%s serialized_size=%d duration_ms=%d",
            name,
            type(result).__name__,
            size,
            duration_ms,
        )
        return result
