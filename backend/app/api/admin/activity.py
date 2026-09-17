"""Admin: global activity log + errors views."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ...admin_auth import current_admin
from ...admin_models import AdminUser
from ...db import get_db
from ...models import ActivityLog, StoryQueue, TelegramAccount

router = APIRouter(tags=["admin-activity"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/activity")
def list_activity(
    db: Db,
    _admin: Annotated[AdminUser, Depends(current_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    account_id: int | None = None,
    user_id: int | None = None,
    event_type: str | None = None,
    level: str | None = None,
    search: str | None = None,
):
    q = db.query(ActivityLog)
    if account_id is not None:
        q = q.filter(ActivityLog.account_id == account_id)
    if user_id is not None:
        acc_ids = [
            r[0] for r in db.query(TelegramAccount.id).filter(TelegramAccount.user_id == user_id).all()
        ] or [-1]
        q = q.filter(ActivityLog.account_id.in_(acc_ids))
    if event_type:
        q = q.filter(ActivityLog.event_type.ilike(f"%{event_type}%"))
    if level:
        q = q.filter(ActivityLog.level == level.upper())
    if search:
        q = q.filter(ActivityLog.message.ilike(f"%{search}%"))
    total = q.count()
    items = (
        q.order_by(ActivityLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": i.id,
                "account_id": i.account_id,
                "level": i.level,
                "event_type": i.event_type,
                "message": i.message,
                "metadata": i.meta_json,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in items
        ],
    }


@router.get("/errors")
def list_errors(
    db: Db,
    _admin: Annotated[AdminUser, Depends(current_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    component: str | None = None,
    level: str | None = None,
    search: str | None = None,
):
    """Errors = activity logs with ERROR/CRITICAL level, grouped by message."""
    q = db.query(ActivityLog).filter(ActivityLog.level.in_(("ERROR", "CRITICAL")))
    if component:
        like = f"%{component}%"
        q = q.filter(or_(ActivityLog.event_type.ilike(like), ActivityLog.message.ilike(like)))
    if level:
        q = q.filter(ActivityLog.level == level.upper())
    if search:
        q = q.filter(ActivityLog.message.ilike(f"%{search}%"))
    total = q.count()
    rows = (
        db.query(
            ActivityLog.message,
            func.count(ActivityLog.id).label("count"),
            func.min(ActivityLog.created_at).label("first_seen"),
            func.max(ActivityLog.created_at).label("last_seen"),
            func.max(ActivityLog.level).label("level"),
            func.max(ActivityLog.event_type).label("event_type"),
        )
        .filter(ActivityLog.level.in_(("ERROR", "CRITICAL")))
        .group_by(ActivityLog.message)
        .order_by(func.max(ActivityLog.created_at).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "message": r.message[:500],
                "count": r.count,
                "first_seen": r.first_seen.isoformat() if r.first_seen else None,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                "level": r.level,
                "event_type": r.event_type,
            }
            for r in rows
        ],
    }
