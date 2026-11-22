"""Read-only, narrowly scoped MCP runtime inventory for HML bootstrap.

Not mounted automatically. Deployment requires explicit operational review.
No secret values, arbitrary paths, or mutation are exposed.
"""
from __future__ import annotations

import os
from pathlib import Path
from fastapi import APIRouter, Depends, Header, HTTPException

router = APIRouter(prefix="/mcp-runtime-hml", tags=["mcp-runtime-hml"])
ALLOWED = frozenset({"main.py", "ops_broker.py", "docker-compose.mcp.yml"})
ROOT = Path("/srv/connectors/vitrine-vps-mcp")
TOKEN_ENV = "MCP_RUNTIME_HML_INSPECT_TOKEN"


def authorize(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise HTTPException(status_code=503, detail="inspection_not_configured")
    if authorization != "Bearer " + token:
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/inventory", dependencies=[Depends(authorize)])
def inventory() -> dict:
    """Return metadata only, never contents or environment variables."""
    root = ROOT.resolve(strict=True)
    if root != ROOT or not root.is_dir():
        raise HTTPException(status_code=503, detail="runtime_unavailable")
    result = {}
    for filename in sorted(ALLOWED):
        target = ROOT / filename
        if target.is_symlink():
            result[filename] = {"present": False, "reason": "symlink_denied"}
            continue
        try:
            st = target.stat()
        except FileNotFoundError:
            result[filename] = {"present": False}
            continue
        if not target.is_file() or target.resolve() != root / filename:
            result[filename] = {"present": False, "reason": "not_regular_file"}
            continue
        result[filename] = {"present": True, "size_bytes": st.st_size}
    return {"environment": "hml", "files": result}
