from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from server import (
    audit_snapshot,
    docker_status,
    factory_inventory,
    git_status,
    laravel_status,
    mcp,
    queue_status,
    system_health,
)

N8N_BASE_URL = os.getenv("N8N_BASE_URL", "http://n8n:5678").rstrip("/")
N8N_TIMEOUT = float(os.getenv("N8N_TIMEOUT", "10"))


def _step(code: str, title: str, tool: str, requires_confirmation: bool = False) -> dict[str, Any]:
    return {"code": code, "title": title, "tool": tool, "requires_confirmation": requires_confirmation}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def supervisor_overview() -> dict[str, Any]:
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "system": system_health(),
        "docker": docker_status(),
        "git": git_status(),
        "laravel": laravel_status(),
        "queue": queue_status(),
        "factory": factory_inventory(),
        "n8n": n8n_health(),
    }


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def supervisor_plan(objective: str) -> dict[str, Any]:
    normalized = " ".join(objective.lower().split())
    steps: list[dict[str, Any]] = [
        _step("audit", "Coletar retrato operacional completo", "audit_snapshot"),
        _step("git", "Verificar divergências entre VPS e GitHub", "git_status"),
        _step("factory", "Inventariar comandos, builds e pedidos da Factory", "factory_inventory"),
    ]
    if any(word in normalized for word in ("homolog", "teste", "qualidade", "qa")):
        steps.extend([
            _step("tests", "Executar testes Laravel", "run_laravel_tests", True),
            _step("qa", "Executar QA da Factory", "run_factory_command:factory:smart-qa2", True),
        ])
    if any(word in normalized for word in ("build", "produz", "produto", "factory")):
        steps.extend([
            _step("health", "Validar saúde do motor da Factory", "run_factory_command:factory:health", True),
            _step("produce", "Produzir ou continuar pedido selecionado", "run_factory_command:factory:produce-request", True),
        ])
    if any(word in normalized for word in ("deploy", "public", "implanta", "atualiza")):
        steps.extend([
            _step("release", "Validar status de release", "run_factory_command:factory:release-status", True),
            _step("deploy", "Implantar branch aprovada", "deploy_git_branch", True),
        ])
    if any(word in normalized for word in ("n8n", "automação", "workflow", "fluxo")):
        steps.append(_step("n8n", "Validar disponibilidade do n8n", "n8n_health"))
    return {
        "objective": objective,
        "mode": "plan_only",
        "execution_policy": "Toda mudança exige confirm='EXECUTAR' e ferramenta permitida pelo broker.",
        "steps": steps,
    }


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def n8n_health() -> dict[str, Any]:
    candidates = ("/healthz", "/healthz/readiness", "/")
    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=N8N_TIMEOUT, follow_redirects=False) as client:
        for path in candidates:
            try:
                response = client.get(f"{N8N_BASE_URL}{path}")
                results.append({"path": path, "status_code": response.status_code, "reachable": True})
                if response.status_code < 500:
                    break
            except Exception as exc:
                results.append({"path": path, "reachable": False, "error": str(exc)})
    return {
        "base_url": N8N_BASE_URL,
        "reachable": any(item.get("reachable") for item in results),
        "checks": results,
    }


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
def supervisor_audit() -> dict[str, Any]:
    snapshot = audit_snapshot()
    snapshot["n8n"] = n8n_health()
    snapshot["supervisor_version"] = "1.0.0"
    return snapshot
