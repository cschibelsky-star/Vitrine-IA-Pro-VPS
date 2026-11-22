"""Optional authenticated VIA backup operations router.

Registration in the broker is intentionally a separate deployment gate.
"""
from __future__ import annotations
import os
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from via_backup_restore import verify_via_backup

router = APIRouter(prefix="/via-backup", tags=["via-backup"])

class BackupRequest(BaseModel):
    backup_name: str = Field(min_length=20, max_length=128)
    expected_sha256: str = Field(min_length=64, max_length=64)

def auth(authorization: str | None = Header(default=None)) -> None:
    token = os.getenv("OPS_BROKER_TOKEN", "")
    if not token or authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="unauthorized")

@router.post("/verify", dependencies=[Depends(auth)])
def verify(req: BackupRequest) -> dict:
    try:
        return verify_via_backup(req.backup_name, req.expected_sha256, restore=False)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=type(exc).__name__) from None

@router.post("/restore-isolated", dependencies=[Depends(auth)])
def restore_isolated(req: BackupRequest) -> dict:
    if os.getenv("VIA_ISOLATED_RESTORE_ENABLED") != "true":
        raise HTTPException(status_code=403, detail="restore_disabled")
    try:
        return verify_via_backup(req.backup_name, req.expected_sha256, restore=True)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=type(exc).__name__) from None
