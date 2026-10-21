"""Server-enforced gates for existing Super Centro Compose execution.

The caller may request an operation, never supply verification evidence. This
adapter derives project, registry, workspace and build provenance on the server.
It deliberately does not create a generic proxy to the V5 or the emergency tool.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from foundation import orchestration


def _git_head(run: Any, repository: Path) -> str | None:
    r = run(["git", "rev-parse", "HEAD"], repository, timeout=30)
    head = str(r.get("stdout", "")).strip()
    return head if r.get("ok") and len(head) == 40 and all(c in "0123456789abcdef" for c in head) else None


def _clean(run: Any, repository: Path) -> bool:
    r = run(["git", "status", "--porcelain"], repository, timeout=30)
    return bool(r.get("ok") and not str(r.get("stdout", "")).strip())


def _receipt_path(workspace: Path, service: str) -> Path:
    # Service is validated by the existing _safe_compose_service before this.
    return workspace / ".orchestrator" / ("build-" + service + ".json")


def _image_id(run: Any, project_name: str, service: str) -> str | None:
    # --format restricts output to the immutable image digest, not image metadata.
    tag = project_name + "-" + service + ":latest"
    r = run(["docker", "image", "inspect", "--format", "{{.Id}}", tag],
            Path("/"), timeout=30)
    value = str(r.get("stdout", "")).strip()
    return value if r.get("ok") and value.startswith("sha256:") and len(value) == 71 else None


def _identity(run: Any, repository: Path, compose: Path, project_name: str,
              service: str) -> dict[str, str] | None:
    head = _git_head(run, repository)
    image_id = _image_id(run, project_name, service)
    if head is None or image_id is None:
        return None
    return {"head": head, "compose_sha256": hashlib.sha256(compose.read_bytes()).hexdigest(),
            "image_id": image_id}


def verify_build(run: Any, workspace: Path, repository: Path, compose: Path,
                 project_name: str, service: str) -> bool:
    target = _receipt_path(workspace, service)
    if not target.is_file():
        return False
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
        identity = _identity(run, repository, compose, project_name, service)
        return identity is not None and record == identity
    except (OSError, ValueError, TypeError):
        return False


def remember_build(run: Any, workspace: Path, repository: Path, compose: Path,
                   project_name: str, service: str) -> bool:
    identity = _identity(run, repository, compose, project_name, service)
    if identity is None:
        return False
    receipt_dir = workspace / ".orchestrator"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    target = _receipt_path(workspace, service)
    temporary = target.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(identity, sort_keys=True), encoding="utf-8")
        os.replace(temporary, target)
        return True
    except OSError:
        return False


def _registry_alignment(project_id: str, project: Mapping[str, Any],
                        legacy_root: Path) -> bool | None:
    target = legacy_root / (project_id + ".json")
    if not target.is_file():
        # Some projects are managed exclusively by Super Centro.
        return None
    try:
        legacy = json.loads(target.read_text(encoding="utf-8"))
        return orchestration.equivalent_manifest(project, legacy)
    except (OSError, ValueError, TypeError):
        return False


def preflight(operation: str, project_id: str, project: Mapping[str, Any],
              *, confirm: str, run: Any, workspace: Path, repository: Path,
              compose: Path, project_name: str, service: str,
              legacy_registry: Path) -> dict[str, Any]:
    operation_key = {"build": "compose_build", "up": "compose_up",
                     "restart": "compose_restart"}.get(operation)
    if operation_key is None:
        return {"ok": False, "error": "operation_not_governed"}

    # HML is classified from the actual registered manifest. Production is never
    # authorized through this endpoint, even with an elevated confirmation.
    environment = orchestration.classify_project(project)
    if environment != "homologation":
        return {"ok": False, "error": "target_not_verified_hml", "environment": environment}

    aligned = _registry_alignment(project_id, project, legacy_registry)
    if aligned is False:
        return {"ok": False, "error": "registry_drift_detected"}

    if not _clean(run, repository):
        return {"ok": False, "error": "uncommitted_source_not_approved"}

    isolated = (
        project_id not in ("vitrine-site-prod", "conheca-sumare-prod")
        and "prod" not in project_name.lower()
        and "prod" not in compose.name.lower()
        and compose.is_file() and repository in compose.parents
    )
    evidence = {"isolated_target": isolated}
    if operation == "up":
        evidence["build_passed"] = verify_build(run, workspace, repository, compose,
                                                 project_name, service)
    capability = {"build": "docker_build", "up": "docker_up",
                  "restart": "docker_restart"}[operation]
    adapters = [{"id": "super", "healthy": True, "project_supported": True,
                 "policy_allowed": True, "capabilities": [capability]}]
    decision = orchestration.plan(operation_key, project, adapters,
                                  confirm=confirm, verified=evidence,
                                  registries_aligned=aligned)
    # Avoid exposing filesystem paths or any runtime configuration in responses.
    return decision
