"""Operational catalog for the Superconector V2 HML pilot."""
from dataclasses import dataclass
from pathlib import Path

from assessor_snapshot import FILES as ASSESSOR_FILES, PROJECT as ASSESSOR_PROJECT


@dataclass(frozen=True)
class HmlProject:
    project_id: str
    docker_project: str
    compose_file: str
    services: tuple
    snapshot_prefix: str
    snapshot_paths: tuple

    @property
    def root(self):
        return Path("/srv/projects") / self.project_id / "repository"


PILOT = {
    project.project_id: project for project in (
        HmlProject(
            "assessor-online-pr137-current-hml", "assessor-pr137-current-hml",
            "docker-compose.assessor-laravel-hml.yml",
            ("assessor_laravel",), "assessor-hml", ASSESSOR_FILES,
        ),
        HmlProject(
            "cockpit-admin-v1-hml", "cockpit-admin-v1-hml", "docker-compose.cockpit-hml.yml",
            ("cockpit_app", "cockpit_web"), "cockpit-hml",
            ("config/cockpit-applications.php", "routes/cockpit.php"),
        ),
    )
}


def catalog():
    return [{
        "project_id": p.project_id,
        "environment": "homologation",
        "compose_file": p.compose_file,
        "services": list(p.services),
        "operations": ["project_hml_snapshot", "project_hml_release_preflight"] + (
            ["project_hml_database_backup"] if p.project_id == ASSESSOR_PROJECT else []
        ),
        "snapshot_files": list(p.snapshot_paths),
    } for p in PILOT.values()]
