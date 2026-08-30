from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Date, func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActivityLog, Story, StoryQueue, StoryView, TelegramAccount
from .deps import require_api_token

logger = logging.getLogger("storywatcher.api.dashboard")

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_api_token)])

Db = Annotated[Session, Depends(get_db)]


def _day_start(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/dashboard")
def dashboard(db: Db):
    now = datetime.now(timezone.utc)
    today = _day_start(now)

    accounts = db.query(TelegramAccount).all()
    active_accounts = sum(
        1 for a in accounts if a.status in ("ACTIVE", "PAUSED") or a.monitoring
    )
    monitoring_on = sum(1 for a in accounts if a.monitoring)

    viewed_today = db.query(func.count(StoryView.id)).filter(StoryView.viewed_at >= today).scalar() or 0
    in_queue = (
        db.query(func.count(StoryQueue.id))
        .filter(StoryQueue.status.in_(["PENDING", "WAITING_DELAY", "PROCESSING"]))
        .scalar()
        or 0
    )
    stories_total = db.query(func.count(Story.id)).scalar() or 0

    # Skips and failures come from the activity log over the last 24h.
    day_ago = now - timedelta(days=1)
    skipped = (
        db.query(func.count(ActivityLog.id))
        .filter(ActivityLog.event_type == "story_skipped", ActivityLog.created_at >= day_ago)
        .scalar()
        or 0
    )
    errors = (
        db.query(func.count(ActivityLog.id))
        .filter(ActivityLog.level.in_(["ERROR", "CRITICAL"]), ActivityLog.created_at >= day_ago)
        .scalar()
        or 0
    )

    # Views by hour (today).
    hours = []
    for h in range(24):
        start = today + timedelta(hours=h)
        end = start + timedelta(hours=1)
        cnt = (
            db.query(func.count(StoryView.id))
            .filter(StoryView.viewed_at >= start, StoryView.viewed_at < end)
            .scalar()
            or 0
        )
        hours.append({"hour": h, "count": cnt})

    # Views by day (last 14 days).
    days = []
    for d in range(13, -1, -1):
        start = _day_start(now) - timedelta(days=d)
        end = start + timedelta(days=1)
        cnt = (
            db.query(func.count(StoryView.id))
            .filter(StoryView.viewed_at >= start, StoryView.viewed_at < end)
            .scalar()
            or 0
        )
        days.append({"day": start.isoformat(), "count": cnt})

    # Recent activity.
    recent = (
        db.query(ActivityLog)
        .order_by(ActivityLog.created_at.desc())
        .limit(15)
        .all()
    )

    return {
        "accounts": {
            "total": len(accounts),
            "active": active_accounts,
            "monitoring_on": monitoring_on,
        },
        "cards": {
            "accounts": len(accounts),
            "monitoring": monitoring_on,
            "viewed_today": viewed_today,
            "in_queue": in_queue,
            "stories": stories_total,
            "skipped": skipped,
            "errors": errors,
        },
        "charts": {
            "views_by_hour": hours,
            "views_by_day": days,
        },
        "recent": [
            {
                "id": a.id,
                "account_id": a.account_id,
                "event_type": a.event_type,
                "level": a.level,
                "message": a.message,
                "created_at": a.created_at,
            }
            for a in recent
        ],
    }


@router.get("/stats")
def stats(db: Db, days: int = 7):
    now = datetime.now(timezone.utc)
    start = _day_start(now) - timedelta(days=max(days - 1, 0))

    def count(model, *criteria) -> int:
        q = db.query(func.count(model.id))
        for c in criteria:
            q = q.filter(c)
        return q.scalar() or 0

    views_total = count(StoryView, StoryView.viewed_at >= start)
    likes_total = count(ActivityLog, ActivityLog.event_type == "story_liked", ActivityLog.created_at >= start)
    skipped_total = count(ActivityLog, ActivityLog.event_type == "story_skipped", ActivityLog.created_at >= start)
    errors_total = count(ActivityLog, ActivityLog.level.in_(["ERROR", "CRITICAL"]), ActivityLog.created_at >= start)
    stories_found = count(Story, Story.discovered_at >= start)

    # Views grouped by calendar day, filled with zeros for gaps.
    views_by_day_raw = dict(
        db.query(StoryView.viewed_at.cast(Date), func.count(StoryView.id))
        .filter(StoryView.viewed_at >= start)
        .group_by(StoryView.viewed_at.cast(Date))
        .all()
    )
    views_by_day = []
    for d in range(max(days - 1, 0), -1, -1):
        day = (_day_start(now) - timedelta(days=d)).date()
        views_by_day.append({"day": day.isoformat(), "count": views_by_day_raw.get(day, 0)})

    # Views grouped by hour of day (0-23), filled with zeros.
    views_by_hour_raw = {
        int(h): int(c)
        for h, c in db.query(
            func.extract("hour", StoryView.viewed_at), func.count(StoryView.id)
        )
        .filter(StoryView.viewed_at >= start)
        .group_by(func.extract("hour", StoryView.viewed_at))
        .all()
    }
    views_by_hour = [
        {"hour": h, "count": int(views_by_hour_raw.get(h, 0))} for h in range(24)
    ]

    def source_map(model) -> dict:
        return {
            k: v
            for k, v in db.query(model.source, func.count(model.id))
            .group_by(model.source)
            .all()
        }

    stories_by_source = source_map(Story)
    views_by_source = source_map(StoryView)
    queue_by_status = dict(
        db.query(StoryQueue.status, func.count(StoryQueue.id))
        .group_by(StoryQueue.status)
        .all()
    )
    activity_by_type = dict(
        db.query(ActivityLog.event_type, func.count(ActivityLog.id))
        .filter(ActivityLog.created_at >= start)
        .group_by(ActivityLog.event_type)
        .order_by(func.count(ActivityLog.id).desc())
        .all()
    )

    return {
        "period_days": days,
        "views_total": views_total,
        "likes_total": likes_total,
        "skipped_total": skipped_total,
        "errors_total": errors_total,
        "stories_found": stories_found,
        "views_by_day": views_by_day,
        "views_by_hour": views_by_hour,
        "views_by_source": views_by_source,
        "stories_by_source": stories_by_source,
        "queue_by_status": queue_by_status,
        "activity_by_type": activity_by_type,
    }