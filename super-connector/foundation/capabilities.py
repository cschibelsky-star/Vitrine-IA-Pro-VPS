from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import main


STACK_MARKERS = {
    "laravel": ["artisan", "composer.json"],
    "php": ["composer.json"],
    "node": ["package.json"],
    "python": ["requirements.txt", "pyproject.toml"],
    "docker": ["docker-compose.yml", "compose.yml", "compose.yaml"],
}

CAPABILITY_REQUIREMENTS = {
    "laravel": {"git", "files", "docker", "php", "laravel", "logs"},
    "php": {"git", "files", "php"},
    "node": {"git", "files", "docker", "logs"},
    "python": {"git", "files", "docker", "logs"},
    "docker": {"docker", "logs"},
}

AVAILABLE_CAPABILITIES = {
    "health",
    "projects",
    "discovery",
    "git",
    "files",
    "docker",
    "logs",
    "php",
    "laravel",
}

CONNECTOR_ROUTING_POLICY: dict[str, dict[str, Any]] = {
    "super": {
        "role": "orchestrator",
        "preferred_for": {"policy", "discovery", "capability_routing", "safe_files", "advanced_ops"},
        "fallback_priority": 10,
        "preserve_capabilities": True,
    },
    "vps_operations": {
        "role": "infrastructure_specialist",
        "preferred_for": {"vps", "github", "hostgator", "infrastructure", "docker", "network", "tls", "backup"},
        "fallback_priority": 20,
        "preserve_capabilities": True,
    },
    "v5": {
        "role": "project_runtime_specialist",
        "preferred_for": {"projects", "runtime", "compose", "git", "laravel", "secrets"},
        "fallback_priority": 30,
        "preserve_capabilities": True,
    },
    "v4": {
        "role": "break_glass_recovery",
        "preferred_for": {"recovery", "restore", "emergency", "diagnostic"},
        "fallback_priority": 90,
        "preserve_capabilities": True,
        "normal_route": False,
    },
}

_CONNECTOR_ROOT = Path(__file__).resolve().parents[1]
_CAPABILITY_MANIFEST = _CONNECTOR_ROOT / "capability-manifest.json"
_TOOL_SOURCE_FILES = (
    _CONNECTOR_ROOT / "main.py",
    _CONNECTOR_ROOT / "materialize_entrypoint.py",
    _CONNECTOR_ROOT / "foundation_entrypoint.py",
)


def _is_mcp_tool_decorator(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Attribute) and target.attr == "tool"


def _registered_tool_names() -> tuple[set[str], list[dict[str, str]]]:
    tools: set[str] = set()
    errors: list[dict[str, str]] = []
    for source in _TOOL_SOURCE_FILES:
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, SyntaxError) as exc:
            errors.append({"file": source.name, "error": type(exc).__name__})
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(_is_mcp_tool_decorator(decorator) for decorator in node.decorator_list):
                tools.add(node.name)
    return tools, errors


def capability_regression_report() -> dict[str, Any]:
    try:
        manifest = json.loads(_CAPABILITY_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "error": "capability_manifest_unavailable",
            "detail": type(exc).__name__,
            "manifest": str(_CAPABILITY_MANIFEST),
        }

    required_raw = manifest.get("required_tools", [])
    if not isinstance(required_raw, list) or not all(isinstance(item, str) and item for item in required_raw):
        return {"ok": False, "error": "invalid_capability_manifest"}

    required = set(required_raw)
    registered, source_errors = _registered_tool_names()
    missing = sorted(required - registered)
    added = sorted(registered - required)
    duplicate_manifest_entries = sorted({name for name in required_raw if required_raw.count(name) > 1})
    ok = not missing and not source_errors and not duplicate_manifest_entries

    return {
        "ok": ok,
        "connector": manifest.get("connector"),
        "schema_version": manifest.get("schema_version"),
        "policy": manifest.get("policy"),
        "required_tool_count": len(required),
        "registered_tool_count": len(registered),
        "missing_tools": missing,
        "added_tools": added,
        "source_errors": source_errors,
        "duplicate_manifest_entries": duplicate_manifest_entries,
        "deployment_blocked": not ok,
        "recommendation": "catalog_matches_manifest" if ok else "block_deploy_until_catalog_regression_is_resolved",
    }


def recommend_connector(capability: str, available_connectors: list[str] | None = None, recovery_mode: bool = False) -> dict[str, Any]:
    requested = str(capability or "").strip().lower().replace("-", "_").replace(" ", "_")
    available = set(available_connectors or CONNECTOR_ROUTING_POLICY.keys())
    candidates: list[dict[str, Any]] = []
    for connector, config in CONNECTOR_ROUTING_POLICY.items():
        if connector not in available:
            continue
        preferred = set(config.get("preferred_for", set()))
        is_v4 = connector == "v4"
        if is_v4 and not recovery_mode and requested not in {"recovery", "restore", "emergency", "diagnostic"}:
            continue
        specialty_match = requested in preferred
        score = 100 if specialty_match else 10
        score -= int(config.get("fallback_priority", 50))
        if connector == "super" and requested in {"policy", "discovery", "capability_routing", "safe_files", "advanced_ops"}:
            score += 40
        if connector == "vps_operations" and requested in {"vps", "github", "hostgator", "infrastructure", "docker", "network", "tls", "backup"}:
            score += 40
        if connector == "v5" and requested in {"projects", "runtime", "compose", "git", "laravel", "secrets"}:
            score += 40
        if is_v4 and recovery_mode:
            score += 60
        candidates.append({
            "connector": connector,
            "role": config.get("role"),
            "specialty_match": specialty_match,
            "score": score,
            "fallback_priority": config.get("fallback_priority"),
            "preserve_capabilities": bool(config.get("preserve_capabilities", True)),
        })
    candidates.sort(key=lambda item: (-int(item["score"]), int(item["fallback_priority"])))
    selected = candidates[0]["connector"] if candidates else None
    return {
        "ok": bool(selected),
        "capability": requested,
        "selected_connector": selected,
        "candidates": candidates,
        "policy": {
            "keep_useful_capabilities": True,
            "remove_only_true_duplicates": True,
            "github_source_of_truth": True,
            "preserve_before_reconcile": True,
            "v4_break_glass_only": True,
            "route_by_capability_health_security": True,
        },
    }


def discover(project_id: str) -> dict[str, Any]:
    project = main._load_project(project_id)
    repository = main._repository(project)
    detected: set[str] = set()
    evidence: dict[str, list[str]] = {}
    for stack, markers in STACK_MARKERS.items():
        found = [marker for marker in markers if (repository / marker).exists()]
        if found:
            detected.add(stack)
            evidence[stack] = found
    compose_cfg = str(project.get("docker", {}).get("compose_file", "") or "").strip()
    if compose_cfg:
        detected.add("docker")
        evidence.setdefault("docker", []).append(compose_cfg)
    required: set[str] = {"health", "projects", "discovery"}
    for stack in detected:
        required |= CAPABILITY_REQUIREMENTS.get(stack, set())
    return {
        "ok": True,
        "project_id": project_id,
        "repository": str(repository),
        "detected_stack": sorted(detected),
        "evidence": evidence,
        "required_capabilities": sorted(required),
    }


def capability_check(project_id: str) -> dict[str, Any]:
    result = discover(project_id)
    required = set(result["required_capabilities"])
    available = set(AVAILABLE_CAPABILITIES)
    missing = sorted(required - available)
    catalog = capability_regression_report()
    return {
        **result,
        "available_capabilities": sorted(available),
        "missing_capabilities": missing,
        "tool_catalog_ok": bool(catalog.get("ok")),
        "missing_tools": catalog.get("missing_tools", []),
        "added_tools": catalog.get("added_tools", []),
        "fully_supported": not missing and bool(catalog.get("ok")),
    }


def gap_report(project_id: str) -> dict[str, Any]:
    check = capability_check(project_id)
    missing_capabilities = check["missing_capabilities"]
    missing_tools = check.get("missing_tools", [])
    catalog_ok = bool(check.get("tool_catalog_ok"))
    return {
        "ok": True,
        "project_id": project_id,
        "detected_stack": check["detected_stack"],
        "missing_capabilities": missing_capabilities,
        "missing_tools": missing_tools,
        "added_tools": check.get("added_tools", []),
        "tool_catalog_ok": catalog_ok,
        "gap_count": len(missing_capabilities) + len(missing_tools),
        "recommendation": (
            "no_capability_gap_detected"
            if not missing_capabilities and catalog_ok
            else "block_deploy_until_capability_gap_is_resolved"
        ),
    }
