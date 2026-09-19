from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import main


def _safe_path(project_id: str, path: str) -> tuple[Path, Path]:
    project = main._load_project(project_id)
    repository = main._repository(project).resolve()
    relative = Path(str(path or "").strip())
    if not str(relative) or relative.is_absolute():
        raise ValueError("invalid_relative_path")
    target = (repository / relative).resolve()
    try:
        target.relative_to(repository)
    except ValueError as exc:
        raise PermissionError("path_outside_repository") from exc
    return repository, target


def read_safe(project_id: str, path: str, max_bytes: int = 100000) -> dict[str, Any]:
    max_bytes = max(1, min(int(max_bytes), 1_000_000))
    try:
        repository, target = _safe_path(project_id, path)
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        return {"ok": False, "error": str(exc), "project_id": project_id, "path": path}

    if not target.is_file():
        return {"ok": False, "error": "file_not_found", "project_id": project_id, "path": path}

    data = target.read_bytes()
    truncated = len(data) > max_bytes
    payload = data[:max_bytes]
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "file_not_utf8", "project_id": project_id, "path": path}

    result = {
        "ok": True,
        "project_id": project_id,
        "repository": str(repository),
        "path": str(target.relative_to(repository)),
        "content": content,
        "bytes_total": len(data),
        "bytes_returned": len(payload),
        "truncated": truncated,
    }
    main._audit("files.read_safe", {"project_id": project_id, "path": path, "max_bytes": max_bytes}, {"ok": True, "truncated": truncated})
    return result


def read_lines(project_id: str, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:
    start_line = max(1, int(start_line))
    end_line = max(start_line, min(int(end_line), start_line + 1999))
    result = read_safe(project_id, path, max_bytes=1_000_000)
    if not result.get("ok"):
        return result

    lines = result["content"].splitlines()
    selected = lines[start_line - 1:end_line]
    return {
        "ok": True,
        "project_id": project_id,
        "path": result["path"],
        "start_line": start_line,
        "end_line": min(end_line, len(lines)),
        "total_lines": len(lines),
        "content": "\n".join(selected),
    }



def replace_exact(project_id: str, path: str, old: str, new: str, confirm: str = "") -> dict[str, Any]:
    if confirm != "EXECUTAR":
        return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
    if not isinstance(old, str) or not old or not isinstance(new, str):
        return {"ok": False, "error": "invalid_replace_arguments", "project_id": project_id, "path": path}
    try:
        repository, target = _safe_path(project_id, path)
    except (FileNotFoundError, ValueError, PermissionError, KeyError) as exc:
        return {"ok": False, "error": str(exc), "project_id": project_id, "path": path}
    if not target.is_file() or target.is_symlink():
        return {"ok": False, "error": "file_not_found_or_symlink", "project_id": project_id, "path": path}
    data = target.read_bytes()
    if len(data) > 1_000_000:
        return {"ok": False, "error": "file_too_large", "project_id": project_id, "path": path}
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "file_not_utf8", "project_id": project_id, "path": path}
    occurrences = content.count(old)
    if occurrences != 1:
        result = {"ok": False, "error": "expected_exactly_one_match", "matches": occurrences, "project_id": project_id, "path": path}
        main._audit("files.replace_exact", {"project_id": project_id, "path": path}, result)
        return result
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = target.with_name(f".{target.name}.bak-{stamp}")
    backup.write_bytes(data)
    updated = content.replace(old, new, 1)
    tmp = target.with_name(f".{target.name}.tmp-{stamp}")
    tmp.write_text(updated, encoding="utf-8")
    os.replace(tmp, target)
    before_sha256 = hashlib.sha256(data).hexdigest()
    after_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    result = {
        "ok": True,
        "status": "replaced",
        "project_id": project_id,
        "repository": str(repository),
        "path": str(target.relative_to(repository)),
        "backup_path": str(backup.relative_to(repository)),
        "matches": 1,
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
    }
    main._audit("files.replace_exact", {"project_id": project_id, "path": path}, {"ok": True, "backup_path": result["backup_path"], "before_sha256": before_sha256, "after_sha256": after_sha256})
    return result
