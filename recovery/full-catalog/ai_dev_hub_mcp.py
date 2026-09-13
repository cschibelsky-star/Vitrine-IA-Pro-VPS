from __future__ import annotations

from typing import Any
from server import mcp
from ai_dev_hub_tools import ai_dev_chat as _ai_dev_chat, ai_dev_compare as _ai_dev_compare, ai_dev_code_review as _ai_dev_code_review, ai_dev_models as _ai_dev_models, ai_dev_usage as _ai_dev_usage

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def ai_dev_chat(project_id: str, prompt: str, profile: str = "balanced", model: str = "", provider: str = "roteia", system: str = "") -> dict[str, Any]:
    return _ai_dev_chat(project_id, prompt, profile, model, provider, system)

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def ai_dev_compare(project_id: str, prompt: str, models: list[str] | None = None, provider: str = "roteia", system: str = "") -> dict[str, Any]:
    return _ai_dev_compare(project_id, prompt, models, provider, system)

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
def ai_dev_code_review(project_id: str, prompt: str, profile: str = "balanced", model: str = "", provider: str = "roteia") -> dict[str, Any]:
    return _ai_dev_code_review(project_id, prompt, profile, model, provider)

@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def ai_dev_models(provider: str = "roteia", tier: str = "", modality: str = "text") -> dict[str, Any]:
    return _ai_dev_models(provider, tier, modality)

@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def ai_dev_usage(project_id: str = "vitrine-ia-pro-core") -> dict[str, Any]:
    return _ai_dev_usage(project_id)
