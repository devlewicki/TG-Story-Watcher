"""Admin API routers."""
from __future__ import annotations

from fastapi import APIRouter

from . import (
    activity,
    analytics,
    auth,
    backups,
    dashboard,
    queue,
    security,
    services,
    settings,
    stories,
    users,
    accounts,
    worker,
)

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(users.router)
router.include_router(accounts.router)
router.include_router(stories.router)
router.include_router(queue.router)
router.include_router(worker.router)
router.include_router(services.router)
router.include_router(analytics.router)
router.include_router(activity.router)  # includes /activity + /errors
router.include_router(security.router)
router.include_router(settings.router)
router.include_router(backups.router)
