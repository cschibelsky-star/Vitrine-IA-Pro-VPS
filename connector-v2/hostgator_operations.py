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

router = APIRouter(prefix="/hostgator")

BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
TIMEOUT = int(os.getenv("HOSTGATOR_OPS_TIMEOUT", "60"))
HOST = os.getenv("HOSTGATOR_SSH_HOST", "").strip()
USER = os.getenv("HOSTGATOR_SSH_USER", "").strip()
PORT = os.getenv("HOSTGATOR_SSH_PORT", "2222").strip()
KEY_FILE = os.getenv("HOSTGATOR_SSH_KEY_FILE", "/root/.ssh/hostgator_ops").strip()
HOME_ROOT = os.getenv("HOSTGATOR_HOME_ROOT", "/home1/cris1649").rstrip("/")
ALLOWED_ROOTS = tuple(item.strip().strip("/") for item in os.getenv("HOSTGATOR_ALLOWED_ROOTS", "public_html,vitrine-ai-pro,factory.vitrineaipro.com.br,conhecasumare.com.br").split(",") if item.strip())
BLOCKED_NAMES = {".env", ".env.production", ".env.local", ".htpasswd", "id_rsa", "id_ed25519", "hostgator_ops", "privkey.pem", "fullchain.pem"}
ALLOWED_TEXT_SUFFIXES = {".php", ".html", ".htm", ".css", ".js", ".json", ".md", ".txt", ".xml", ".yml", ".yaml", ".ini", ".conf", ".csv", ".sql"}

class RootRequest(BaseModel):
    root: str = Field(min_length=1, max_length=120)

class ReadFileRequest(BaseModel):
    root: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=400)
    max_bytes: int = Field(default=100000, ge=1, le=500000)

def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")

def audit(action: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat(), "scope": "hostgator", "action": action, "payload": payload, "result": {"ok": bool(result.get("ok")), "exit_code": result.get("exit_code"), "error": result.get("error")}}
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

def connection_config() -> dict[str, str]:
    missing = []
    if not HOST: missing.append("HOSTGATOR_SSH_HOST")
    if not USER: missing.append("HOSTGATOR_SSH_USER")
    if missing:
        raise HTTPException(status_code=503, detail={"missing_environment": missing})
    return {"host": HOST, "user": USER, "port": PORT, "key_file": KEY_FILE}

def ssh_base() -> list[str]:
    cfg = connection_config()
    return ["ssh", "-p", cfg["port"], "-i", cfg["key_file"], "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15", f'{cfg["user"]}@{cfg["host"]}']

def run_remote(command: str) -> dict[str, Any]:
    try:
        proc = subprocess.run([*ssh_base(), command], text=True, capture_output=True, timeout=TIMEOUT, check=False, env={**os.environ, "LC_ALL": "C.UTF-8"})
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "stdout": proc.stdout[-100000:], "stderr": proc.stderr[-20000:]}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "exit_code": 124, "stdout": exc.stdout or "", "stderr": "timeout"}
    except OSError as exc:
        return {"ok": False, "exit_code": 127, "stdout": "", "stderr": type(exc).__name__, "error": "ssh_client_unavailable"}

def normalize_root(root: str) -> str:
    candidate = root.strip().strip("/")
    if candidate not in ALLOWED_ROOTS:
        raise HTTPException(status_code=403, detail="hostgator_root_not_allowed")
    return candidate

def remote_root(root: str) -> str:
    return f"{HOME_ROOT}/{normalize_root(root)}"

def validate_relative_path(path: str) -> str:
    pure = PurePosixPath(path.strip())
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise HTTPException(status_code=422, detail="invalid_relative_path")
    if any(part in BLOCKED_NAMES or part.startswith(".env") for part in pure.parts):
        raise HTTPException(status_code=403, detail="sensitive_path_blocked")
    if PurePosixPath(pure.name).suffix.lower() not in ALLOWED_TEXT_SUFFIXES:
        raise HTTPException(status_code=403, detail="file_type_not_allowed")
    return pure.as_posix()

@router.get("/health", dependencies=[Depends(auth)])
def hostgator_health() -> dict[str, Any]:
    result = run_remote("printf 'HOSTGATOR_OK\\n'; pwd; git --version 2>/dev/null || true")
    response = {"ok": result["ok"] and "HOSTGATOR_OK" in result.get("stdout", ""), "host": HOST or None, "user": USER or None, "port": PORT, "home_root": HOME_ROOT, "allowed_roots": list(ALLOWED_ROOTS), "remote": result}
    audit("health", {}, response)
    return response

@router.post("/git/status", dependencies=[Depends(auth)])
def hostgator_git_status(req: RootRequest) -> dict[str, Any]:
    qroot = shlex.quote(remote_root(req.root))
    command = f"cd -- {qroot} && git rev-parse --is-inside-work-tree >/dev/null 2>&1 && printf 'BRANCH=' && git branch --show-current && printf 'HEAD=' && git rev-parse HEAD && printf 'ORIGIN=' && git remote get-url origin 2>/dev/null || true; cd -- {qroot} && git status --short --branch"
    result = run_remote(command)
    response = {"ok": result["ok"], "root": req.root, "remote": result}
    audit("git_status", req.model_dump(), response)
    return response

@router.post("/git/compare", dependencies=[Depends(auth)])
def hostgator_git_compare(req: RootRequest) -> dict[str, Any]:
    qroot = shlex.quote(remote_root(req.root))
    command = f"cd -- {qroot} && branch=$(git branch --show-current) && head=$(git rev-parse HEAD) && origin=$(git remote get-url origin) && remote_head=$(git ls-remote origin \"refs/heads/$branch\" | awk '{{print $1}}') && printf 'BRANCH=%s\\nHEAD=%s\\nREMOTE_HEAD=%s\\nORIGIN=%s\\n' \"$branch\" \"$head\" \"$remote_head\" \"$origin\" && if [ -n \"$remote_head\" ] && [ \"$head\" = \"$remote_head\" ]; then printf 'SYNC=equal\\n'; else printf 'SYNC=different\\n'; fi"
    result = run_remote(command)
    response = {"ok": result["ok"], "root": req.root, "remote": result}
    audit("git_compare", req.model_dump(), response)
    return response

@router.post("/read-file", dependencies=[Depends(auth)])
def hostgator_read_file(req: ReadFileRequest) -> dict[str, Any]:
    relative = validate_relative_path(req.path)
    target = shlex.quote(f"{remote_root(req.root)}/{relative}")
    result = run_remote(f"test -f {target} && head -c {int(req.max_bytes)} -- {target}")
    response = {"ok": result["ok"], "root": req.root, "path": relative, "content": result.get("stdout", "") if result["ok"] else "", "stderr": result.get("stderr", "") if not result["ok"] else ""}
    audit("read_file", {"root": req.root, "path": relative, "max_bytes": req.max_bytes}, response)
    return response
