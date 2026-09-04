from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from project_file_operations import ProjectFileOperationError, safe_project_file
from project_shared_operations import _safe_shared_file

router = APIRouter(prefix="/projects")

MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")


class ProjectReadRequest(BaseModel):
    project_id: str
    path: str
    start_line: int = Field(default=1, ge=1, le=1000000)
    end_line: int = Field(default=400, ge=1, le=1000000)


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _load_manifest(project_id: str) -> dict[str, Any]:
    value = str(project_id or "").strip().lower()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise HTTPException(status_code=422, detail="invalid_project_id")
    path = (MANIFEST_ROOT / f"{value}.json").resolve()
    if MANIFEST_ROOT not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="manifest_not_found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="manifest_invalid") from exc
    if data.get("id") != value:
        raise HTTPException(status_code=422, detail="manifest_id_mismatch")
    return data


def _read_text(candidate: Path, start_line: int, end_line: int) -> tuple[str, int, int, int]:
    try:
        text = candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="file_not_utf8") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="file_read_failed") from exc

    lines = text.splitlines()
    total = len(lines)
    if total == 0:
        return "", 1, 0, 0
    start = min(start_line, total)
    end = min(max(end_line, start), total)
    return "\n".join(lines[start - 1:end]), start, end, total


@router.post("/read-file", dependencies=[Depends(auth)])
def project_read_file(req: ProjectReadRequest) -> dict[str, Any]:
    manifest = _load_manifest(req.project_id)
    raw = str(req.path or "").strip().replace("\\", "/")

    if raw.startswith("shared/"):
        parts = raw.split("/", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise HTTPException(status_code=422, detail="invalid_shared_path")
        shared_directory, relative_path = parts[1], parts[2]
        relative, candidate = _safe_shared_file(manifest, shared_directory, relative_path)
        content, start, end, total = _read_text(candidate, req.start_line, req.end_line)
        return {
            "ok": True,
            "project_id": req.project_id,
            "scope": "shared",
            "shared_directory": shared_directory,
            "path": f"shared/{shared_directory}/{relative}",
            "start_line": start,
            "end_line": end,
            "total_lines": total,
            "content": content,
        }

    workspace = Path(str(manifest.get("workspace_root", ""))).resolve()
    repository = (workspace / str(manifest.get("repository", {}).get("directory", "repository"))).resolve()
    try:
        relative, candidate = safe_project_file(repository, raw, must_exist=True)
    except ProjectFileOperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    content, start, end, total = _read_text(candidate, req.start_line, req.end_line)
    return {
        "ok": True,
        "project_id": req.project_id,
        "scope": "repository",
        "path": relative,
        "start_line": start,
        "end_line": end,
        "total_lines": total,
        "content": content,
    }
