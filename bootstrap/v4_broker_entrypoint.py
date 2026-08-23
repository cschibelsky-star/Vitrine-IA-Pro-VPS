from __future__ import annotations

import ops_broker as legacy

from project_manager_operations import router as project_manager_router
from project_read_operations import router as project_read_router
from project_shared_operations import router as project_shared_router
from project_explicit_operations import router as project_explicit_router
from project_deployment_engine import router as project_deployment_router

app = legacy.app

for router in (
    project_manager_router,
    project_read_router,
    project_shared_router,
    project_explicit_router,
    project_deployment_router,
):
    app.include_router(router)
