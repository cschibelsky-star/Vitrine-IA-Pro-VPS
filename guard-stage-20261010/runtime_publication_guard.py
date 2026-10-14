"""Fail-closed adapter for independent executors during source reconciliation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def preflight(project_id: str, loader, *, workspace_root: str = "", operation: str = "") -> dict[str, Any] | None:
    if operation in {"status", "logs", "config"}:
        return None
    try:
        source = json.loads(Path(__file__).with_name("publication_sources.json").read_text())["conheca-sumare"]
        if source["production_enabled"] is not False:
            raise ValueError("adapter requires reviewed reconciliation policy")
        if workspace_root:
            manifest = {"workspace_root": workspace_root}
        else:
            manifest = loader(project_id)
        root = str(manifest.get("workspace_root") or manifest.get("workspace", {}).get("root", ""))
        repository_dir = str(manifest.get("repository", {}).get("directory", "repository"))
        paths = (Path(root).resolve(), (Path(root) / repository_dir).resolve())
        protected = (
            project_id in source["production_project_ids"] + source["homologation_project_ids"]
            or any(name in path.parts for name in source["production_root_names"] for path in paths)
            or any(host in json.dumps(manifest.get("domains", {})) for host in source["production_hosts"])
        )
    except Exception:
        return {"ok": False, "error": "canonical_source_policy_unavailable", "project_id": project_id}
    if protected:
        return {"ok": False, "error": "canonical_production_reconciliation_pending", "project_id": project_id,
                "required_executor": "reviewed_project_manager_homologation"}
    return None
