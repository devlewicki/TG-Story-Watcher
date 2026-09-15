"""Admin dashboard: global system overview."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ...admin_auth import current_admin
from ...admin_models import AdminUser, SystemEvent
from ...db import get_db
from ...models import (
    AccountStatus,
    Story,
    StoryQueue,
    StoryView,
    TelegramAccount,
    User,
)
from ...workers import worker_control

router = APIRouter(tags=["admin-dashboard"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/dashboard")
def admin_dashboard(db: Db, admin: Annotated[AdminUser, Depends(current_admin)]):
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    users_total = db.query(func.count(User.id)).scalar() or 0
    accounts_total = db.query(func.count(TelegramAccount.id)).scalar() or 0
    accounts_by_status = dict(
        db.query(TelegramAccount.status, func.count(TelegramAccount.id))
        .group_by(TelegramAccount.status)
        .all()
    )
    accounts_active = accounts_by_status.get(AccountStatus.ACTIVE.value, 0)

    stories_total = db.query(func.count(Story.id)).scalar() or 0
    views_today = (
        db.query(func.count(StoryView.id)).filter(StoryView.viewed_at >= day_ago).scalar()
        or 0
    )

    queue_by_status = dict(
        db.query(StoryQueue.status, func.count(StoryQueue.id))
        .group_by(StoryQueue.status)
        .all()
    )
    queue_active = sum(
        queue_by_status.get(s, 0)
        for s in ("PENDING", "WAITING_DELAY", "PROCESSING")
    )
    queue_failed = queue_by_status.get("FAILED", 0)

    # Worker: heartbeat + published status + pause flag
    hb_age = worker_control.heartbeat_age_seconds()
    worker_status = worker_control.read_status() or {}
    running = worker_control.worker_running()
    paused = worker_control.is_paused()

    # Services health
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False

    redis_ok = False
    try:
        import redis as redis_lib

        from ...config import get_settings

        client = redis_lib.Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        redis_ok = bool(client.ping())
    except Exception:  # noqa: BLE001
        redis_ok = False

    recent_events = (
        db.query(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(10).all()
    )

    return {
        "users": users_total,
        "accounts": {
            "total": accounts_total,
            "active": accounts_active,
            "by_status": accounts_by_status,
        },
        "stories": stories_total,
        "queue": {
            "total": sum(queue_by_status.values()),
            "active": queue_active,
            "failed": queue_failed,
            "by_status": queue_by_status,
        },
        "views_today": views_today,
        "worker": {
            "running": running,
            "paused": paused,
            "heartbeat_age": hb_age,
            "status": worker_status,
        },
        "services": {
            "backend": {"ok": True},
            "worker": {"ok": running, "paused": paused},
            "postgres": {"ok": db_ok},
            "redis": {"ok": redis_ok},
        },
        "recent_events": [
            {
                "id": e.id,
                "component": e.component,
                "event_type": e.event_type,
                "severity": e.severity,
                "message": e.message,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in recent_events
        ],
    }
