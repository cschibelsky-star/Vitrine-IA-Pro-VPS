from __future__ import annotations

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

# Only capabilities actually exposed by the Super v0.2 foundation should be
# advertised here. Missing capabilities are intentional: the gap report must
# be truthful and drive the next implementation wave.
AVAILABLE_CAPABILITIES = {
    "health",
    "projects",
    "discovery",
    "git",
    "docker",
    "logs",
    "laravel",
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
    return {
        **result,
        "available_capabilities": sorted(available),
        "missing_capabilities": missing,
        "fully_supported": not missing,
    }


def gap_report(project_id: str) -> dict[str, Any]:
    check = capability_check(project_id)
    return {
        "ok": True,
        "project_id": project_id,
        "detected_stack": check["detected_stack"],
        "missing_capabilities": check["missing_capabilities"],
        "gap_count": len(check["missing_capabilities"]),
        "recommendation": (
            "no_capability_gap_detected"
            if not check["missing_capabilities"]
            else "implement_missing_capabilities_before_mutating_project"
        ),
    }
