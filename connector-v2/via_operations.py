from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/via")

BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
VIA_ROOT = Path(os.getenv("VIA_WORKSPACE_ROOT", "/srv/via")).resolve()
TIMEOUT = int(os.getenv("VIA_OPS_TIMEOUT", "300"))
MAX_READ_BYTES = int(os.getenv("VIA_MAX_READ_BYTES", "100000"))
BLOCKED_NAMES = {".env", ".env.local", ".env.production", ".htpasswd", "id_rsa", "id_ed25519", "hostgator_ops", "privkey.pem", "fullchain.pem"}
ALLOWED_TEXT_SUFFIXES = {".py", ".php", ".html", ".htm", ".css", ".js", ".json", ".md", ".txt", ".xml", ".yml", ".yaml", ".ini", ".conf", ".csv", ".sh"}
ALLOWED_COMMANDS = {"python", "python3", "php", "composer", "npm", "node", "git", "bash", "sh"}


class PathRequest(BaseModel):
    path: str = Field(default=".", max_length=400)
    max_entries: int = Field(default=500, ge=1, le=2000)


class ReadRequest(BaseModel):
    path: str = Field(min_length=1, max_length=400)
    max_bytes: int = Field(default=100000, ge=1, le=500000)


class WriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=400)
    content: str = Field(max_length=500000)
    confirm: str = ""


class ExecuteRequest(BaseModel):
    command: list[str] = Field(min_length=1, max_length=30)
    cwd: str = Field(default=".", max_length=400)
    timeout: int = Field(default=300, ge=1, le=1200)
    confirm: str = ""


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def audit(action: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    safe = dict(payload)
    if "confirm" in safe:
        safe["confirm"] = "***"
    if "content" in safe:
        safe["content"] = f"<{len(str(payload.get('content', '')))} bytes>"
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": "via",
        "action": action,
        "payload": safe,
        "result": {"ok": bool(result.get("ok")), "exit_code": result.get("exit_code"), "error": result.get("error")},
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def require_execute(confirm: str) -> None:
    if confirm != "EXECUTAR":
        raise HTTPException(status_code=409, detail="explicit_confirmation_required")


def resolve_path(relative: str, *, must_exist: bool = False) -> Path:
    raw = relative.strip() or "."
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts:
        raise HTTPException(status_code=422, detail="invalid_relative_path")
    if any(part in BLOCKED_NAMES or part.startswith(".env") for part in pure.parts):
        raise HTTPException(status_code=403, detail="sensitive_path_blocked")
    target = (VIA_ROOT / Path(*pure.parts)).resolve()
    try:
        target.relative_to(VIA_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path_outside_via_workspace") from exc
    if must_exist and not target.exists():
        raise HTTPException(status_code=404, detail="path_not_found")
    return target


def validate_text_file(path: Path) -> None:
    if path.suffix.lower() not in ALLOWED_TEXT_SUFFIXES:
        raise HTTPException(status_code=403, detail="file_type_not_allowed")


@router.get("/health", dependencies=[Depends(auth)])
def via_health() -> dict[str, Any]:
    result = {"ok": VIA_ROOT.is_dir(), "workspace_root": str(VIA_ROOT), "exists": VIA_ROOT.exists(), "is_dir": VIA_ROOT.is_dir()}
    audit("health", {}, result)
    return result


@router.post("/list-files", dependencies=[Depends(auth)])
def via_list_files(req: PathRequest) -> dict[str, Any]:
    root = resolve_path(req.path, must_exist=True)
    if not root.is_dir():
        raise HTTPException(status_code=422, detail="not_a_directory")
    entries: list[str] = []
    for item in sorted(root.rglob("*")):
        try:
            relative = item.relative_to(VIA_ROOT)
        except ValueError:
            continue
        if any(part in BLOCKED_NAMES or part.startswith(".env") for part in relative.parts):
            continue
        entries.append(relative.as_posix() + ("/" if item.is_dir() else ""))
        if len(entries) >= req.max_entries:
            break
    result = {"ok": True, "path": req.path, "entries": entries, "truncated": len(entries) >= req.max_entries}
    audit("list_files", req.model_dump(), result)
    return result


@router.post("/read-file", dependencies=[Depends(auth)])
def via_read_file(req: ReadRequest) -> dict[str, Any]:
    target = resolve_path(req.path, must_exist=True)
    if not target.is_file():
        raise HTTPException(status_code=422, detail="not_a_file")
    validate_text_file(target)
    limit = min(req.max_bytes, MAX_READ_BYTES)
    content = target.read_bytes()[:limit].decode("utf-8", errors="replace")
    result = {"ok": True, "path": req.path, "content": content, "truncated": target.stat().st_size > limit}
    audit("read_file", {"path": req.path, "max_bytes": limit}, result)
    return result


@router.post("/write-file", dependencies=[Depends(auth)])
def via_write_file(req: WriteRequest) -> dict[str, Any]:
    require_execute(req.confirm)
    target = resolve_path(req.path)
    validate_text_file(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")
    result = {"ok": True, "path": req.path, "bytes": len(req.content.encode("utf-8"))}
    audit("write_file", req.model_dump(), result)
    return result


@router.post("/execute-command", dependencies=[Depends(auth)])
def via_execute_command(req: ExecuteRequest) -> dict[str, Any]:
    require_execute(req.confirm)
    if not req.command or req.command[0] not in ALLOWED_COMMANDS:
        raise HTTPException(status_code=403, detail="command_not_allowed")
    if any("\x00" in arg or "\n" in arg or "\r" in arg for arg in req.command):
        raise HTTPException(status_code=422, detail="invalid_command_argument")
    cwd = resolve_path(req.cwd, must_exist=True)
    if not cwd.is_dir():
        raise HTTPException(status_code=422, detail="cwd_not_directory")
    try:
        proc = subprocess.run(req.command, cwd=str(cwd), text=True, capture_output=True, timeout=min(req.timeout, TIMEOUT), check=False, env={**os.environ, "LC_ALL": "C.UTF-8"})
        result = {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": proc.stdout[-100000:], "stderr": proc.stderr[-20000:]}
    except subprocess.TimeoutExpired as exc:
        result = {"ok": False, "exit_code": 124, "stdout": exc.stdout or "", "stderr": "timeout", "error": "timeout"}
    audit("execute_command", req.model_dump(), result)
    return result
