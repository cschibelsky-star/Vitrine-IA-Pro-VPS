from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

CONNECTOR_ID = "vitrine_ops"
CONNECTOR_DISPLAY_NAME = "Vitrine IA Pro — Centro Operacional"
CONNECTOR_VERSION = "2.1.0-stabilization.1"
PROJECT_MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests"))


def _safe_project_id(project_id: str) -> str:
    value = str(project_id or "").strip().lower()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise ValueError("invalid_project_id")
    return value


def project_context(project_id: str) -> dict[str, Any]:
    project_id = _safe_project_id(project_id)
    path = (PROJECT_MANIFEST_ROOT / f"{project_id}.json").resolve()
    root = PROJECT_MANIFEST_ROOT.resolve()
    if root not in path.parents or not path.is_file():
        return {"ok": False, "error": "manifest_not_found", "project_id": project_id}
    data = json.loads(path.read_text(encoding="utf-8"))
    workspace = PurePosixPath(data["workspace_root"])
    repository = workspace / data.get("repository", {}).get("directory", "repository")
    docker = data.get("docker", {})
    deployment = data.get("deployment", {})
    return {
        "ok": True,
        "project_id": project_id,
        "name": data.get("name", project_id),
        "workspace_root": str(workspace),
        "repository_root": str(repository),
        "repository_url": data.get("repository", {}).get("url"),
        "branch": data.get("repository", {}).get("branch", "main"),
        "compose_file": docker.get("compose_file", "docker-compose.yml"),
        "docker_project": docker.get("project_name", project_id),
        "service": docker.get("service"),
        "backup_root": data.get("backup_root"),
        "homologation": deployment.get("homologation", {}),
        "production": deployment.get("production", {}),
    }


def connector_health() -> dict[str, Any]:
    projects = []
    if PROJECT_MANIFEST_ROOT.is_dir():
        projects = sorted(path.stem for path in PROJECT_MANIFEST_ROOT.glob("*.json") if path.is_file())
    return {
        "ok": True,
        "connector_id": CONNECTOR_ID,
        "display_name": CONNECTOR_DISPLAY_NAME,
        "version": CONNECTOR_VERSION,
        "registry": "single-fastmcp-main",
        "manifest_root": str(PROJECT_MANIFEST_ROOT),
        "projects": projects,
        "capabilities": [
            "connector_health",
            "project_context",
            "project_status",
            "project_deploy",
            "tvsumare_operations",
        ],
    }
