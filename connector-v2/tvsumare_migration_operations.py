from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/tvsumare/migration")

TV_ROOT = Path(os.getenv("TVSUMARE_ROOT", "/srv/tvsumare")).resolve()
REPOSITORY = TV_ROOT / "repository"
SNAPSHOTS = TV_ROOT / "snapshots" / "hostgator"
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("TVSUMARE_OPS_TIMEOUT", "1200"))

DEFAULT_REPOSITORY = os.getenv(
    "TVSUMARE_GIT_URL",
    "https://github.com/cschibelsky-star/TVSUMARE_ENTERPRISE.git",
)
DEFAULT_BRANCH = os.getenv("TVSUMARE_GIT_BRANCH", "main")


class CloneRequest(BaseModel):
    repository_url: str = DEFAULT_REPOSITORY
    branch: str = DEFAULT_BRANCH


class SnapshotRequest(BaseModel):
    remote_path: str = "public_html"


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def audit(action: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scope": "tvsumare-migration",
        "action": action,
        "payload": payload,
        "result": result,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd or TV_ROOT),
            text=True,
            capture_output=True,
            timeout=TIMEOUT,
            check=False,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-50000:],
            "stderr": proc.stderr[-20000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": 124,
            "stdout": (exc.stdout or "")[-50000:],
            "stderr": "timeout",
        }


def directory_manifest(root: Path) -> dict[str, Any]:
    files = 0
    directories = 0
    total_bytes = 0
    extensions: dict[str, int] = {}

    for path in root.rglob("*"):
        if path.is_dir():
            directories += 1
            continue
        if not path.is_file():
            continue
        files += 1
        try:
            total_bytes += path.stat().st_size
        except OSError:
            pass
        suffix = path.suffix.lower() or "[sem-extensao]"
        extensions[suffix] = extensions.get(suffix, 0) + 1

    return {
        "files": files,
        "directories": directories,
        "total_bytes": total_bytes,
        "top_extensions": dict(
            sorted(extensions.items(), key=lambda item: item[1], reverse=True)[:20]
        ),
    }


@router.post("/clone", dependencies=[Depends(auth)])
def clone_repository(req: CloneRequest) -> dict[str, Any]:
    TV_ROOT.mkdir(parents=True, exist_ok=True)

    if (REPOSITORY / ".git").exists():
        fetch = run(["git", "fetch", "--all", "--prune"], REPOSITORY)
        if not fetch["ok"]:
            audit("clone_repository_fetch_failed", req.model_dump(), fetch)
            return fetch

        checkout = run(["git", "checkout", req.branch], REPOSITORY)
        if not checkout["ok"]:
            audit("clone_repository_checkout_failed", req.model_dump(), checkout)
            return checkout

        update = run(["git", "pull", "--ff-only", "origin", req.branch], REPOSITORY)
        result = {
            "ok": update["ok"],
            "operation": "updated",
            "repository": str(REPOSITORY),
            "branch": req.branch,
            "fetch": fetch,
            "checkout": checkout,
            "update": update,
        }
        audit("clone_repository", req.model_dump(), result)
        return result

    if REPOSITORY.exists() and any(REPOSITORY.iterdir()):
        result = {
            "ok": False,
            "exit_code": 409,
            "stderr": "repository_directory_not_empty",
            "repository": str(REPOSITORY),
        }
        audit("clone_repository_refused", req.model_dump(), result)
        return result

    REPOSITORY.parent.mkdir(parents=True, exist_ok=True)
    if REPOSITORY.exists():
        REPOSITORY.rmdir()

    clone = run(
        [
            "git",
            "clone",
            "--branch",
            req.branch,
            "--single-branch",
            req.repository_url,
            str(REPOSITORY),
        ],
        TV_ROOT,
    )
    result = {
        "ok": clone["ok"],
        "operation": "cloned",
        "repository": str(REPOSITORY),
        "branch": req.branch,
        "result": clone,
    }
    audit("clone_repository", req.model_dump(), result)
    return result


@router.post("/hostgator-snapshot", dependencies=[Depends(auth)])
def import_hostgator_snapshot(req: SnapshotRequest) -> dict[str, Any]:
    host = os.getenv("HOSTGATOR_SSH_HOST", "").strip()
    user = os.getenv("HOSTGATOR_SSH_USER", "").strip()
    port = os.getenv("HOSTGATOR_SSH_PORT", "2222").strip()
    key_file = os.getenv("HOSTGATOR_SSH_KEY_FILE", "/root/.ssh/id_ed25519").strip()

    missing = [
        name
        for name, value in {
            "HOSTGATOR_SSH_HOST": host,
            "HOSTGATOR_SSH_USER": user,
        }.items()
        if not value
    ]
    if missing:
        result = {"ok": False, "missing_environment": missing}
        audit("hostgator_snapshot_missing_environment", req.model_dump(), result)
        return result

    if req.remote_path.startswith("/") or ".." in Path(req.remote_path).parts:
        raise HTTPException(status_code=422, detail="invalid_remote_path")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snapshot_root = SNAPSHOTS / stamp
    payload_root = snapshot_root / "payload"
    payload_root.mkdir(parents=True, exist_ok=False)

    source = f"{user}@{host}:{req.remote_path}"
    command = [
        "scp",
        "-r",
        "-p",
        "-P",
        port,
        "-i",
        key_file,
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        source,
        str(payload_root),
    ]
    transfer = run(command, TV_ROOT)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_host": host,
        "source_user": user,
        "source_path": req.remote_path,
        "destination": str(snapshot_root),
        "transfer_ok": transfer["ok"],
    }

    if transfer["ok"]:
        copied_root = payload_root / Path(req.remote_path).name
        if copied_root.exists():
            manifest["inventory"] = directory_manifest(copied_root)

    manifest_path = snapshot_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = {
        "ok": transfer["ok"],
        "snapshot": str(snapshot_root),
        "manifest": str(manifest_path),
        "transfer": transfer,
    }
    audit("hostgator_snapshot", req.model_dump(), result)
    return result
