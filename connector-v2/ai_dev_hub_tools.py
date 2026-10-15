from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, parse, request


def _base_url() -> str:
    value = os.getenv("AI_DEV_HUB_BASE_URL", "").strip().rstrip("/")
    if not value:
        raise RuntimeError("AI_DEV_HUB_BASE_URL não configurada no conector")
    return value


def _token() -> str:
    value = os.getenv("AI_DEV_HUB_INTERNAL_TOKEN", "").strip()
    if not value:
        raise RuntimeError("AI_DEV_HUB_INTERNAL_TOKEN não configurado no conector")
    return value


def _call(method: str, path: str, *, project_id: str = "", payload: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> dict[str, Any]:
    url = _base_url() + path
    if query:
        clean = {key: value for key, value in query.items() if value not in (None, "")}
        if clean:
            url += "?" + parse.urlencode(clean)

    body = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {_token()}",
        "User-Agent": "Vitrine-IA-Pro-MCP/ai-dev-hub",
    }

    if project_id:
        headers["X-Vitrine-Project"] = project_id

    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=body, headers=headers, method=method.upper())

    try:
        with request.urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                raise RuntimeError("Resposta inválida do AI Dev Hub")
            return data
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI Dev Hub HTTP {exc.code}: {raw[:2000]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Falha de conexão com AI Dev Hub: {exc.reason}") from exc


def ai_dev_chat(
    project_id: str,
    prompt: str,
    profile: str = "balanced",
    model: str = "",
    provider: str = "roteia",
    system: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "provider": provider,
        "profile": profile,
        "prompt": prompt,
    }
    if model:
        payload["model"] = model
    if system:
        payload["system"] = system
    return _call("POST", "/api/internal/ai-dev/chat", project_id=project_id, payload=payload)


def ai_dev_compare(
    project_id: str,
    prompt: str,
    models: list[str] | None = None,
    provider: str = "roteia",
    system: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "provider": provider,
        "prompt": prompt,
    }
    if models:
        payload["models"] = models
    if system:
        payload["system"] = system
    return _call("POST", "/api/internal/ai-dev/compare", project_id=project_id, payload=payload)


def ai_dev_code_review(
    project_id: str,
    prompt: str,
    profile: str = "balanced",
    model: str = "",
    provider: str = "roteia",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "provider": provider,
        "profile": profile,
        "prompt": prompt,
    }
    if model:
        payload["model"] = model
    return _call("POST", "/api/internal/ai-dev/code-review", project_id=project_id, payload=payload)


def ai_dev_models(provider: str = "roteia", tier: str = "", modality: str = "text") -> dict[str, Any]:
    return _call(
        "GET",
        "/api/internal/ai-dev/models",
        query={"provider": provider, "tier": tier, "modality": modality},
    )


def ai_dev_usage(project_id: str = "vitrine-ia-pro-core") -> dict[str, Any]:
    return _call("GET", "/api/internal/ai-dev/usage", project_id=project_id)
