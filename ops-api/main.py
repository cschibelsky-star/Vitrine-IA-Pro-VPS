from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI

PROJECT_MANAGER_DIR = Path(__file__).resolve().parent.parent / "project-manager"
if str(PROJECT_MANAGER_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_MANAGER_DIR))

from project_manager_operations import router as project_router  # noqa: E402
from project_shared_operations import router as project_shared_router  # noqa: E402
from project_read_operations import router as project_read_router  # noqa: E402

APP_VERSION = os.getenv("VITRINE_OPS_API_VERSION", "0.1.0")

app = FastAPI(
    title="Vitrine Ops API",
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url=None,
)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "service": "vitrine-ops-api",
        "version": APP_VERSION,
    }


app.include_router(project_router)
app.include_router(project_shared_router)
app.include_router(project_read_router)
