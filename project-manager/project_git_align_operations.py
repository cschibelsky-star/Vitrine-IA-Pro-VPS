from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/projects")

MANIFEST_ROOT = Path(os.getenv("PROJECT_MANIFEST_ROOT", "/app/project-manifests")).resolve()
BROKER_TOKEN = os.getenv("OPS_BROKER_TOKEN", "")
TIMEOUT = int(os.getenv("PROJECT_MANAGER_TIMEOUT", "1200"))
AUDIT_LOG = Path(os.getenv("OPS_AUDIT_LOG", "/var/log/vitrine-ops/audit.jsonl"))
ALLOWED_WORKSPACE_ROOTS = tuple(
    Path(item.strip()).resolve()
    for item in os.getenv("PROJECT_WORKSPACE_ROOTS", "/srv/tvsumare,/srv/projects").split(",")
    if item.strip()
)


class AlignRequest(BaseModel):
    project_id: str
    expected_head: str
    expected_remote_head: str
    recovery_ref: str
    confirm: str = ""


def auth(authorization: str | None = Header(default=None)) -> None:
    if not BROKER_TOKEN or authorization != f"Bearer {BROKER_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _manifest(project_id: str) -> dict[str, Any]:
    if not project_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in project_id):
        raise HTTPException(status_code=422, detail="invalid_project_id")
    path = (MANIFEST_ROOT / f"{project_id}.json").resolve()
    if MANIFEST_ROOT not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="manifest_not_found")
    data = json.loads(path.read_text(encoding="utf-8"))
    root = Path(str(data["workspace_root"])).resolve()
    if not any(_within(root, allowed) for allowed in ALLOWED_WORKSPACE_ROOTS):
        raise HTTPException(status_code=403, detail="workspace_root_blocked")
    return data


def _run(repository: Path, args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repository),
        text=True,
        capture_output=True,
        timeout=TIMEOUT,
        check=False,
        env={**os.environ, "LC_ALL": "C.UTF-8"},
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-16000:],
        "stderr": proc.stderr[-16000:],
    }


def _value(repository: Path, args: list[str]) -> str:
    result=_run(repository,args)
    return result["stdout"].strip() if result["ok"] else ""


def _audit(payload: dict[str, Any], result: dict[str, Any]) -> None:
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        record={
            "at":datetime.now(timezone.utc).isoformat(),
            "scope":"project-manager",
            "action":"project_git_align",
            "project_id":payload.get("project_id",""),
            "payload":{k:v for k,v in payload.items() if k!="confirm"},
            "result":result,
        }
        with AUDIT_LOG.open("a",encoding="utf-8") as handle:
            handle.write(json.dumps(record,ensure_ascii=False)+"\n")
    except OSError:
        pass


@router.post("/git-align", dependencies=[Depends(auth)])
def project_git_align(req: AlignRequest) -> dict[str, Any]:
    payload=req.model_dump()
    if req.confirm!="EXECUTAR":
        raise HTTPException(status_code=422, detail="confirmation_required")
    if not re.fullmatch(r"[0-9a-f]{40}",req.expected_head):
        raise HTTPException(status_code=422, detail="invalid_expected_head")
    if not re.fullmatch(r"[0-9a-f]{40}",req.expected_remote_head):
        raise HTTPException(status_code=422, detail="invalid_expected_remote_head")
    if not re.fullmatch(r"recovery-local/[a-z0-9][a-z0-9._/-]{2,100}",req.recovery_ref):
        raise HTTPException(status_code=422, detail="invalid_recovery_ref")
    if ".." in req.recovery_ref or req.recovery_ref.endswith("/"):
        raise HTTPException(status_code=422, detail="invalid_recovery_ref")

    data=_manifest(req.project_id)
    root=Path(str(data["workspace_root"])).resolve()
    repository=(root/str(data.get("repository",{}).get("directory","repository"))).resolve()
    if not _within(repository,root) or not (repository/".git").is_dir():
        raise HTTPException(status_code=404,detail="repository_not_git")

    configured_branch=str(data.get("repository",{}).get("branch","main")).strip()
    remote_ref=f"origin/{configured_branch}"
    current_branch=_value(repository,["branch","--show-current"])
    current_head=_value(repository,["rev-parse","HEAD"])
    tracked_status=_value(repository,["status","--porcelain","--untracked-files=no"])

    preflight={
        "branch":current_branch,
        "head":current_head,
        "tracked_clean":tracked_status=="",
        "remote_ref":remote_ref,
    }
    if current_branch!=configured_branch:
        result={"ok":False,"stage":"preflight","error":"branch_mismatch","preflight":preflight}; _audit(payload,result); return result
    if current_head!=req.expected_head:
        result={"ok":False,"stage":"preflight","error":"head_mismatch","preflight":preflight}; _audit(payload,result); return result
    if tracked_status!="":
        result={"ok":False,"stage":"preflight","error":"tracked_worktree_dirty","preflight":preflight,"tracked_status":tracked_status}; _audit(payload,result); return result

    fetch=_run(repository,["fetch","origin",configured_branch])
    if not fetch["ok"]:
        result={"ok":False,"stage":"fetch","result":fetch}; _audit(payload,result); return result

    remote_head=_value(repository,["rev-parse","--verify",remote_ref])
    if remote_head!=req.expected_remote_head:
        result={"ok":False,"stage":"preflight","error":"remote_head_mismatch","expected":req.expected_remote_head,"actual":remote_head}; _audit(payload,result); return result

    full_ref=f"refs/heads/{req.recovery_ref}"
    existing=_value(repository,["rev-parse","--verify",full_ref])
    if existing and existing!=current_head:
        result={"ok":False,"stage":"backup","error":"recovery_ref_conflict","existing":existing}; _audit(payload,result); return result
    if not existing:
        create_backup=_run(repository,["update-ref",full_ref,current_head])
        if not create_backup["ok"]:
            result={"ok":False,"stage":"backup","result":create_backup}; _audit(payload,result); return result

    verified_backup=_value(repository,["rev-parse","--verify",full_ref])
    if verified_backup!=current_head:
        result={"ok":False,"stage":"backup","error":"recovery_ref_verify_failed","actual":verified_backup}; _audit(payload,result); return result

    reset=_run(repository,["reset","--hard",remote_ref])
    if not reset["ok"]:
        result={"ok":False,"stage":"reset","recovery_ref":req.recovery_ref,"result":reset}; _audit(payload,result); return result

    final_head=_value(repository,["rev-parse","HEAD"])
    final_branch=_value(repository,["branch","--show-current"])
    final_tracked_status=_value(repository,["status","--porcelain","--untracked-files=no"])
    ok=(final_head==req.expected_remote_head and final_branch==configured_branch and final_tracked_status=="")
    result={
        "ok":ok,
        "project_id":req.project_id,
        "operation":"aligned_to_remote",
        "previous_head":current_head,
        "final_head":final_head,
        "branch":final_branch,
        "recovery_ref":req.recovery_ref,
        "recovery_head":verified_backup,
        "tracked_clean":final_tracked_status=="",
        "reset":reset,
    }
    if not ok:
        result["error"]="postcondition_failed"
    _audit(payload,result)
    return result
