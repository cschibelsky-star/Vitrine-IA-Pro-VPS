from __future__ import annotations

import ipaddress
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
DNS_ALLOWED_ZONE = os.getenv("HOSTGATOR_DNS_ALLOWED_ZONE", "vitrineaipro.com.br").strip().lower().rstrip(".")
DNS_ALLOWED_IPV4S = tuple(item.strip() for item in os.getenv("HOSTGATOR_DNS_ALLOWED_IPV4S", "143.95.219.238").split(",") if item.strip())
BLOCKED_NAMES = {".env", ".env.production", ".env.local", ".htpasswd", "id_rsa", "id_ed25519", "hostgator_ops", "privkey.pem", "fullchain.pem"}
ALLOWED_TEXT_SUFFIXES = {".php", ".html", ".htm", ".css", ".js", ".json", ".md", ".txt", ".xml", ".yml", ".yaml", ".ini", ".conf", ".csv", ".sql"}

class RootRequest(BaseModel):
    root: str = Field(min_length=1, max_length=120)

class ReadFileRequest(BaseModel):
    root: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=400)
    max_bytes: int = Field(default=100000, ge=1, le=500000)

class ListFilesRequest(BaseModel):
    root: str = Field(min_length=1, max_length=120)
    path: str = Field(default=".", min_length=1, max_length=400)
    max_depth: int = Field(default=2, ge=0, le=8)
    max_entries: int = Field(default=1000, ge=1, le=5000)
    include_hidden: bool = False

class DnsStatusRequest(BaseModel):
    hostname: str = Field(min_length=3, max_length=253)

class DnsUpsertRequest(BaseModel):
    hostname: str = Field(min_length=3, max_length=253)
    address: str = Field(min_length=7, max_length=45)
    ttl: int = Field(default=300, ge=60, le=86400)
    confirm: str = Field(default="", max_length=20)

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

def _validate_relative(path: str, allow_dot: bool = False) -> str:
    raw = path.strip()
    if allow_dot and raw in {"", "."}:
        return "."
    pure = PurePosixPath(raw)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise HTTPException(status_code=422, detail="invalid_relative_path")
    if any(part in BLOCKED_NAMES or part.startswith(".env") for part in pure.parts):
        raise HTTPException(status_code=403, detail="sensitive_path_blocked")
    return pure.as_posix()

def validate_relative_path(path: str) -> str:
    relative = _validate_relative(path)
    if PurePosixPath(relative).suffix.lower() not in ALLOWED_TEXT_SUFFIXES:
        raise HTTPException(status_code=403, detail="file_type_not_allowed")
    return relative

def validate_relative_directory(path: str) -> str:
    return _validate_relative(path, allow_dot=True)

def is_sensitive_relative(path: str) -> bool:
    pure = PurePosixPath(path)
    return any(part in BLOCKED_NAMES or part.startswith(".env") for part in pure.parts)

def normalize_dns_hostname(hostname: str) -> str:
    value = str(hostname or "").strip().lower().rstrip(".")
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789.-"
    if not value or any(ch not in allowed for ch in value):
        raise HTTPException(status_code=422, detail="invalid_hostname")
    if value == DNS_ALLOWED_ZONE or not value.endswith("." + DNS_ALLOWED_ZONE):
        raise HTTPException(status_code=403, detail="hostname_not_allowed")
    return value

def normalize_dns_ipv4(address: str) -> str:
    try:
        value = str(ipaddress.ip_address(str(address or "").strip()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_ip_address") from exc
    if ":" in value:
        raise HTTPException(status_code=422, detail="ipv4_required")
    if DNS_ALLOWED_IPV4S and value not in DNS_ALLOWED_IPV4S:
        raise HTTPException(status_code=403, detail="dns_target_not_allowed")
    return value

def run_uapi(module: str, function: str, params: dict[str, str]) -> dict[str, Any]:
    parts = ["uapi", "--output=json", module, function]
    for key, value in params.items():
        parts.append(f"{key}={value}")
    result = run_remote(" ".join(shlex.quote(part) for part in parts))
    if not result.get("ok"):
        return {"ok": False, "error": "uapi_transport_failed", "remote": result}
    try:
        payload = json.loads(result.get("stdout") or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "uapi_invalid_json", "remote": result}
    block = payload.get("result", {}) if isinstance(payload, dict) else {}
    status = int(block.get("status", 0) or 0)
    return {"ok": status == 1, "status": status, "data": block.get("data"), "errors": block.get("errors"), "messages": block.get("messages")}

def fetch_dns_a_records(hostname: str) -> dict[str, Any]:
    host = normalize_dns_hostname(hostname)
    result = run_uapi("ZoneEdit", "fetchzone_records", {"domain": DNS_ALLOWED_ZONE})
    if not result.get("ok"):
        return {"ok": False, "error": "dns_zone_read_failed", "detail": result}
    data = result.get("data") or []
    if isinstance(data, dict):
        data = data.get("records", []) or data.get("zone", []) or []
    records = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower().rstrip(".")
        record_type = str(item.get("type") or "").strip().upper()
        if name != host or record_type != "A":
            continue
        value = item.get("address") or item.get("record") or item.get("data") or ""
        records.append({"name": name, "type": record_type, "value": str(value).strip(), "line": item.get("line"), "ttl": item.get("ttl")})
    return {"ok": True, "hostname": host, "records": records}

@router.get("/health", dependencies=[Depends(auth)])
def hostgator_health() -> dict[str, Any]:
    result = run_remote("printf 'HOSTGATOR_OK\\n'; pwd; git --version 2>/dev/null || true")
    response = {"ok": result["ok"] and "HOSTGATOR_OK" in result.get("stdout", ""), "host": HOST or None, "user": USER or None, "port": PORT, "home_root": HOME_ROOT, "allowed_roots": list(ALLOWED_ROOTS), "remote": result}
    audit("health", {}, response)
    return response

@router.post("/dns/status", dependencies=[Depends(auth)])
def hostgator_dns_status(req: DnsStatusRequest) -> dict[str, Any]:
    result = fetch_dns_a_records(req.hostname)
    audit("dns_status", req.model_dump(), result)
    return result

@router.post("/dns/upsert", dependencies=[Depends(auth)])
def hostgator_dns_upsert(req: DnsUpsertRequest) -> dict[str, Any]:
    if req.confirm != "EXECUTAR":
        raise HTTPException(status_code=409, detail="confirmation_required")
    host = normalize_dns_hostname(req.hostname)
    address = normalize_dns_ipv4(req.address)
    current = fetch_dns_a_records(host)
    if not current.get("ok"):
        audit("dns_upsert", req.model_dump(), current)
        return current
    records = current.get("records", [])
    if any(record.get("value") == address for record in records):
        result = {"ok": True, "status": "unchanged", "hostname": host, "address": address, "ttl": req.ttl}
        audit("dns_upsert", req.model_dump(), result)
        return result
    if records:
        result = {"ok": False, "error": "dns_record_conflict", "hostname": host, "existing": records, "requested_address": address}
        audit("dns_upsert", req.model_dump(), result)
        return result
    created = run_uapi("ZoneEdit", "add_zone_record", {"domain": DNS_ALLOWED_ZONE, "name": host + ".", "type": "A", "address": address, "ttl": str(req.ttl)})
    if not created.get("ok"):
        result = {"ok": False, "error": "dns_record_create_failed", "hostname": host, "detail": created}
        audit("dns_upsert", req.model_dump(), result)
        return result
    verified = fetch_dns_a_records(host)
    ok = bool(verified.get("ok") and any(record.get("value") == address for record in verified.get("records", [])))
    result = {"ok": ok, "status": "created" if ok else "created_unverified", "hostname": host, "address": address, "ttl": req.ttl, "records": verified.get("records", []) if verified.get("ok") else []}
    if not ok:
        result["error"] = "dns_record_verification_failed"
    audit("dns_upsert", req.model_dump(), result)
    return result

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

@router.post("/list-files", dependencies=[Depends(auth)])
def hostgator_list_files(req: ListFilesRequest) -> dict[str, Any]:
    relative = validate_relative_directory(req.path)
    target = remote_root(req.root) if relative == "." else f"{remote_root(req.root)}/{relative}"
    qtarget = shlex.quote(target)
    command = (
        f"test -d {qtarget} && find {qtarget} -mindepth 1 -maxdepth {int(req.max_depth) + 1} "
        f"-printf '%P\\t%y\\t%s\\n' | head -n {int(req.max_entries) + 1}"
    )
    result = run_remote(command)
    entries: list[dict[str, Any]] = []
    raw_lines = result.get("stdout", "").splitlines() if result["ok"] else []
    for line in raw_lines:
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        entry_path, kind, raw_size = parts
        if not entry_path or is_sensitive_relative(entry_path):
            continue
        if not req.include_hidden and any(part.startswith(".") for part in PurePosixPath(entry_path).parts):
            continue
        entry_type = {"d": "directory", "f": "file", "l": "symlink"}.get(kind, "other")
        size = int(raw_size) if entry_type == "file" and raw_size.isdigit() else None
        entries.append({"path": entry_path, "type": entry_type, "size": size})
        if len(entries) >= req.max_entries:
            break
    response = {
        "ok": result["ok"],
        "root": req.root,
        "path": relative,
        "max_depth": req.max_depth,
        "entries": entries,
        "truncated": result["ok"] and len(raw_lines) > req.max_entries,
        "stderr": result.get("stderr", "") if not result["ok"] else "",
    }
    audit("list_files", req.model_dump(), response)
    return response

@router.post("/read-file", dependencies=[Depends(auth)])
def hostgator_read_file(req: ReadFileRequest) -> dict[str, Any]:
    relative = validate_relative_path(req.path)
    target = shlex.quote(f"{remote_root(req.root)}/{relative}")
    result = run_remote(f"test -f {target} && head -c {int(req.max_bytes)} -- {target}")
    response = {"ok": result["ok"], "root": req.root, "path": relative, "content": result.get("stdout", "") if result["ok"] else "", "stderr": result.get("stderr", "") if not result["ok"] else ""}
    audit("read_file", {"root": req.root, "path": relative, "max_bytes": req.max_bytes}, response)
    return response
