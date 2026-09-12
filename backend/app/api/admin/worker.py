"""Admin: worker control."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...admin_auth import client_ip, current_admin, require_admin_permission
from ...admin_models import AdminUser
from ...db import get_db
from ...models import StoryQueue, StoryView
from ...services import admin_audit
from ...workers import worker_control

router = APIRouter(tags=["admin-worker"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/worker")
def worker_status(
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
):
    hb_age = worker_control.heartbeat_age_seconds()
    status = worker_control.read_status() or {}
    running = worker_control.worker_running()
    paused = worker_control.is_paused()

    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    views_today = (
        db.query(func.count(StoryView.id)).filter(StoryView.viewed_at >= day_ago).scalar() or 0
    )
    processed_today = views_today
    queue_active = (
        db.query(func.count(StoryQueue.id))
        .filter(StoryQueue.status.in_(("PENDING", "WAITING_DELAY", "PROCESSING")))
        .scalar() or 0
    )
    return {
        "running": running,
        "paused": paused,
        "pid": status.get("pid"),
        "uptime_seconds": time.time() - float(status.get("started_at", time.time())) if status.get("started_at") else None,
        "heartbeat_age": hb_age,
        "views_today": views_today,
        "queue_active": queue_active,
        "consecutive_errors": status.get("consecutive_errors", 0),
        "status": status,
    }


@router.post("/worker/pause")
def pause_worker(
    request: Request,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    worker_control.set_paused(True)
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="worker.pause",
        ip=client_ip(request),
    )
    return {"ok": True, "paused": True}


@router.post("/worker/resume")
def resume_worker(
    request: Request,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    worker_control.set_paused(False)
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="worker.resume",
        ip=client_ip(request),
    )
    return {"ok": True, "paused": False}


@router.post("/worker/restart")
def restart_worker(
    request: Request,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    """Request a safe restart: the worker finishes its current cycle, closes
    Telethon clients cleanly, then exits; Docker restart policy brings it back."""
    worker_control.request_restart()
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="worker.restart",
        ip=client_ip(request),
    )
    return {"ok": True, "restart_requested": True}
