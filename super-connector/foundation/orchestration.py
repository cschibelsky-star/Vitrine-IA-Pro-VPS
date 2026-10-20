"""Fail-closed, side-effect-free orchestration contract for Vitrine IA Pro.

Different connectors keep different paths and allowlists. This module decides
whether an operation may be routed; it never runs shell, MCP or Docker commands.
Only server-verified evidence should ever be supplied by an executor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

READ = "read"
CONTROLLED = "controlled"
CRITICAL = "critical"

@dataclass(frozen=True)
class Operation:
    capability: str
    risk: str
    routes: tuple[str, ...]
    needs: tuple[str, ...] = ()

# Routes are equivalent *operations*, not interchangeable shell executors.
OPERATIONS: dict[str, Operation] = {
    "health": Operation("health", READ, ("super", "v5", "vps_ops", "v4")),
    "project_inspect": Operation("projects", READ, ("super", "v5", "vps_ops", "v4")),
    "git_status": Operation("git", READ, ("super", "v5", "vps_ops", "v4")),
    "git_reconcile": Operation("git", CONTROLLED, ("super", "v5"), ("tree_preserved",)),
    "compose_build": Operation("docker_build", CONTROLLED, ("super", "v5"), ("isolated_target",)),
    "compose_up": Operation("docker_up", CONTROLLED, ("super", "v5"), ("isolated_target", "build_passed")),
    "compose_restart": Operation("docker_restart", CONTROLLED, ("super", "v5"), ("isolated_target",)),
    "hml_publish": Operation("hml_publication", CONTROLLED, ("super", "v5"), ("hml_tests_passed", "rollback_ready")),
    "production_deploy": Operation("production_deploy", CRITICAL, (), ("cockpit_approved", "hml_tests_passed", "backup_verified", "rollback_ready")),
}

# Errors for which a connector has expressly reported no write.
PRE_EXECUTION_ERRORS = frozenset({
    "controlled_service_not_allowed",
    "controlled_operation_not_allowed",
    "controlled_compose_file_not_allowed",
    "compose_file_not_configured",
    "project_not_registered",
    "tool_not_available",
    "tool_not_supported",
    "capability_not_available",
})

def classify_project(project: Mapping[str, Any]) -> str:
    """Unknown stays unknown; never assume a project is HML."""
    project_id = str(project.get("id", "")).lower()
    docker = project.get("docker") or {}
    project_name = str(docker.get("project_name", "")).lower()
    domains = project.get("domains") or {}
    compose = str(docker.get("compose_file", "")).lower()
    if (project_id.endswith("-prod") or project_name.endswith("-prod")
        or any("prod" in str(k).lower() and domains[k] for k in domains)):
        return "production"
    if (any(token in project_id for token in ("-hml", "-review", "-lab", "-candidate"))
        or "hml" in compose or "review" in compose):
        return "homologation"
    return "unknown"

def equivalent_manifest(super_project: Mapping[str, Any], v5_project: Mapping[str, Any]) -> bool:
    """Compare identity and runtime routing, not unrelated connector settings."""
    a, b = super_project, v5_project
    if a.get("id") != b.get("id"):
        return False
    for k in ("url", "branch", "directory"):
        if (a.get("repository") or {}).get(k) != (b.get("repository") or {}).get(k):
            return False
    if (a.get("workspace") or {}).get("root") != b.get("workspace_root"):
        return False
    for k in ("compose_file", "project_name"):
        if (a.get("docker") or {}).get(k) != (b.get("docker") or {}).get(k):
            return False
    return True

def plan(
    operation: str,
    project: Mapping[str, Any],
    adapters: Sequence[Mapping[str, Any]],
    *,
    confirm: str = "",
    verified: Mapping[str, bool] | None = None,
    registries_aligned: bool | None = None,
) -> dict[str, Any]:
    """Pure preflight. Evidence is trusted only if collected by the executor."""
    op = OPERATIONS.get(str(operation or "").strip())
    if op is None:
        return {"ok": False, "error": "unknown_operation_denied"}
    env = classify_project(project)
    if op.risk != READ:
        if env == "unknown":
            return {"ok": False, "error": "environment_unclassified", "environment": env}
        required_confirmation = "EXECUTAR PRODUCAO" if env == "production" else "EXECUTAR"
        if confirm != required_confirmation:
            return {"ok": False, "error": "authorization_required", "required": required_confirmation}
        if registries_aligned is False:
            return {"ok": False, "error": "registry_drift_detected"}
    evidence = verified or {}
    missing = [item for item in op.needs if evidence.get(item) is not True]
    if env == "production" and op.risk != READ:
        extra = ("cockpit_approved", "hml_tests_passed", "backup_verified", "rollback_ready")
        missing.extend(x for x in extra if evidence.get(x) is not True and x not in missing)
    if missing:
        return {"ok": False, "error": "preflight_incomplete", "environment": env, "missing": missing}
    available: list[str] = []
    for route in op.routes:
        for adapter in adapters:
            if (adapter.get("id") == route and adapter.get("healthy") is True
                and adapter.get("project_supported") is True
                and op.capability in (adapter.get("capabilities") or ())
                and adapter.get("policy_allowed") is True):
                available.append(route)
                break
    if not available:
        return {"ok": False, "error": "no_equivalent_authorized_route", "environment": env}
    return {"ok": True, "operation": operation, "environment": env, "risk": op.risk,
            "selected": available[0], "fallback": available[1:], "capability": op.capability}

def may_fallback(response: Mapping[str, Any], *, mutation_possible: bool = False) -> bool:
    """No retry after timeout, uncertain outcome, partial write or success."""
    return (
        response.get("ok") is False
        and mutation_possible is False
        and response.get("mutated") is not True
        and response.get("error") in PRE_EXECUTION_ERRORS
    )
