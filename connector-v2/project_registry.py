from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    label: str
    root: str
    repository: str
    backup_root: str
    compose_file: str
    service: str
    homologation_domain: str


PROJECTS: dict[str, ProjectContext] = {
    "tvsumare": ProjectContext(
        project_id="tvsumare",
        label="TV Sumaré Enterprise",
        root="/srv/tvsumare",
        repository="/srv/tvsumare/repository",
        backup_root="/srv/backups/tvsumare",
        compose_file="/srv/tvsumare/repository/docker-compose.vps.yml",
        service="web",
        homologation_domain="tv-hml.vitrineiapro.com.br",
    ),
}


def get_project_context(project_id: str) -> dict[str, Any]:
    key=(project_id or "").strip().lower()
    project=PROJECTS.get(key)
    if project is None:
        return {
            "ok": False,
            "error": "unknown_project",
            "project_id": key,
            "known_projects": sorted(PROJECTS),
        }
    return {"ok": True, **asdict(project)}


def list_project_contexts() -> dict[str, Any]:
    return {
        "ok": True,
        "projects": [asdict(PROJECTS[key]) for key in sorted(PROJECTS)],
    }
