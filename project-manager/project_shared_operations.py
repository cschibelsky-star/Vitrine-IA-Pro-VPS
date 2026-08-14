from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/projects")

MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
MAX_SHARED_READ_BYTES = int(os.getenv("PROJECT_SHARED_READ_MAX_BYTES", "1048576"))
ALLOWED_SHARED_SUFFIXES = {".json", ".jsonl", ".log", ".txt", ".csv", ".md"}
BLOCKED_SHARED_DIRECTORIES = {"secrets", "credentials", "private"}


class SharedReadRequest(BaseModel):
    project_id: str
    shared_directory: str
    path: str
    start_line: int = Field(default=1, ge=1, le=1000000)
    end_line: int = Field(default=400, ge=1, le=1000000)


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _safe_project_id(project_id: str) -> str:
    value = str(project_id or "").strip().lower()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise HTTPException(status_code=422, detail="invalid_project_id")
    return value


def _load_manifest(project_id: str) -> dict[str, Any]:
    project_id = _safe_project_id(project_id)
    path = (MANIFEST_ROOT / f"{project_id}.json").resolve()
    if MANIFEST_ROOT not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="manifest_not_found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="manifest_invalid") from exc
    if data.get("id") != project_id:
        raise HTTPException(status_code=422, detail="manifest_id_mismatch")
    return data


def _normalize_relative(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw or raw.startswith("/") or ":" in raw or "\x00" in raw:
        raise HTTPException(status_code=422, detail="invalid_shared_path")
    parts = tuple(part for part in raw.split("/") if part not in ("", "."))
    if not parts or ".." in parts or any(ord(ch) < 32 for ch in raw):
        raise HTTPException(status_code=422, detail="invalid_shared_path")
    return "/".join(parts)


def _safe_shared_file(manifest: dict[str, Any], shared_directory: str, path: str) -> tuple[str, Path]:
    shared_name = str(shared_directory or "").strip()
    declared = {str(item).strip() for item in manifest.get("shared_directories", [])}
    if shared_name not in declared:
        raise HTTPException(status_code=403, detail="shared_directory_not_declared")
    if shared_name.lower() in BLOCKED_SHARED_DIRECTORIES:
        raise HTTPException(status_code=403, detail="shared_directory_blocked")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", shared_name):
        raise HTTPException(status_code=422, detail="invalid_shared_directory")

    relative = _normalize_relative(path)
    workspace = Path(str(manifest.get("workspace_root", ""))).resolve()
    root = (workspace / "shared" / shared_name).resolve()
    candidate = (root / relative).resolve()
    if root != candidate and root not in candidate.parents:
        raise HTTPException(status_code=403, detail="shared_path_outside_scope")

    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise HTTPException(status_code=403, detail="shared_symlink_blocked")
        if not current.exists():
            break

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="shared_file_not_found")
    if candidate.is_symlink():
        raise HTTPException(status_code=403, detail="shared_symlink_blocked")
    if candidate.suffix.lower() not in ALLOWED_SHARED_SUFFIXES:
        raise HTTPException(status_code=403, detail="shared_file_type_blocked")
    size = candidate.stat().st_size
    if size > MAX_SHARED_READ_BYTES:
        raise HTTPException(status_code=413, detail="shared_file_too_large")
    return relative, candidate


@router.post("/shared/read", dependencies=[Depends(auth)])
def project_shared_read(req: SharedReadRequest) -> dict[str, Any]:
    manifest = _load_manifest(req.project_id)
    relative, candidate = _safe_shared_file(manifest, req.shared_directory, req.path)
    try:
        text = candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="shared_file_not_utf8") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="shared_file_read_failed") from exc

    lines = text.splitlines()
    total = len(lines)
    start = min(req.start_line, max(total, 1))
    end = min(max(req.end_line, start), total) if total else 0
    content = "\n".join(lines[start - 1:end]) if total else ""
    return {
        "ok": True,
        "project_id": req.project_id,
        "shared_directory": req.shared_directory,
        "path": relative,
        "start_line": start,
        "end_line": end,
        "total_lines": total,
        "bytes": candidate.stat().st_size,
        "content": content,
    }
