"""Admin: system / user / account analytics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from ...admin_auth import current_admin
from ...admin_models import AdminUser
from ...db import get_db
from ...models import (
    ActivityLog,
    Story,
    StoryQueue,
    StoryView,
    TelegramAccount,
    User,
)

router = APIRouter(tags=["admin-analytics"])
Db = Annotated[Session, Depends(get_db)]

_PERIODS_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30, "90d": 24 * 90}


@router.get("/analytics/system")
def system_analytics(
    db: Db,
    _admin: Annotated[AdminUser, Depends(current_admin)],
    period: str = Query("7d", pattern="^(24h|7d|30d|90d)$"),
):
    hours = _PERIODS_HOURS[period]
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    day_bucket = (
        func.date_trunc(
            "day",
            StoryView.viewed_at.op("AT TIME ZONE")("Europe/Moscow"),
        )
        if str(db.bind.url).startswith("postgresql")
        else func.date(StoryView.viewed_at)
    )
    views_per_day = (
        db.query(day_bucket.label("day"), func.count(StoryView.id))
        .filter(StoryView.viewed_at >= since, StoryView.status == "VIEWED")
        .group_by("day")
        .order_by("day")
        .all()
    )
    active_accounts = (
        db.query(func.count(TelegramAccount.id))
        .filter(TelegramAccount.monitoring.is_(True))
        .scalar()
        or 0
    )
    stories_discovered = (
        db.query(func.count(Story.id)).filter(Story.discovered_at >= since).scalar() or 0
    )
    failed_tasks = (
        db.query(func.count(StoryQueue.id))
        .filter(StoryQueue.status == "FAILED", StoryQueue.completed_at >= since)
        .scalar()
        or 0
    )
    errors_count = (
        db.query(func.count(ActivityLog.id))
        .filter(ActivityLog.level.in_(("ERROR", "CRITICAL", "WARNING")), ActivityLog.created_at >= since)
        .scalar()
        or 0
    )
    flood_waits = (
        db.query(func.count(ActivityLog.id))
        .filter(ActivityLog.event_type.ilike("%flood%"), ActivityLog.created_at >= since)
        .scalar()
        or 0
    )
    new_users = (
        db.query(func.count(User.id)).filter(User.created_at >= since).scalar() or 0
    )
    return {
        "period": period,
        "views_per_day": [
            {"day": (d.isoformat() if hasattr(d, "isoformat") else str(d)), "count": c}
            for d, c in views_per_day
        ],
        "active_accounts": active_accounts,
        "stories_discovered": stories_discovered,
        "failed_tasks": failed_tasks,
        "errors": errors_count,
        "flood_waits": flood_waits,
        "new_users": new_users,
    }


@router.get("/analytics/users/{user_id}")
def user_analytics(
    user_id: int,
    db: Db,
    _admin: Annotated[AdminUser, Depends(current_admin)],
    period: str = Query("7d", pattern="^(24h|7d|30d|90d)$"),
):
    hours = _PERIODS_HOURS[period]
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    acc_ids = [
        r[0] for r in db.query(TelegramAccount.id).filter(TelegramAccount.user_id == user_id).all()
    ] or [-1]
    views = (
        db.query(func.count(StoryView.id))
        .filter(StoryView.account_id.in_(acc_ids), StoryView.viewed_at >= since, StoryView.status == "VIEWED")
        .scalar()
        or 0
    )
    stories = db.query(func.count(Story.id)).filter(Story.account_id.in_(acc_ids)).scalar() or 0
    queue_active = (
        db.query(func.count(StoryQueue.id))
        .filter(StoryQueue.account_id.in_(acc_ids), StoryQueue.status.in_(("PENDING", "WAITING_DELAY", "PROCESSING")))
        .scalar()
        or 0
    )
    errors = (
        db.query(func.count(ActivityLog.id))
        .filter(ActivityLog.account_id.in_(acc_ids), ActivityLog.level.in_(("ERROR", "CRITICAL")), ActivityLog.created_at >= since)
        .scalar()
        or 0
    )
    return {
        "user_id": user_id,
        "period": period,
        "views": views,
        "stories": stories,
        "queue_active": queue_active,
        "errors": errors,
    }


@router.get("/analytics/accounts/{account_id}")
def account_analytics(
    account_id: int,
    db: Db,
    _admin: Annotated[AdminUser, Depends(current_admin)],
    period: str = Query("7d", pattern="^(24h|7d|30d|90d)$"),
):
    hours = _PERIODS_HOURS[period]
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    views = (
        db.query(func.count(StoryView.id))
        .filter(StoryView.account_id == account_id, StoryView.viewed_at >= since, StoryView.status == "VIEWED")
        .scalar()
        or 0
    )
    failures = (
        db.query(func.count(StoryView.id))
        .filter(StoryView.account_id == account_id, StoryView.status == "FAILED", StoryView.viewed_at >= since)
        .scalar()
        or 0
    )
    floods = (
        db.query(func.count(ActivityLog.id))
        .filter(ActivityLog.account_id == account_id, ActivityLog.event_type.ilike("%flood%"), ActivityLog.created_at >= since)
        .scalar()
        or 0
    )
    acc = db.get(TelegramAccount, account_id)
    return {
        "account_id": account_id,
        "period": period,
        "views": views,
        "failures": failures,
        "flood_waits": floods,
        "monitoring": acc.monitoring if acc else None,
        "status": acc.status if acc else None,
    }
