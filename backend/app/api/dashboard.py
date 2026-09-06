from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActivityLog, Story, StoryQueue, StoryView, TelegramAccount
from .deps import require_api_token, current_user_id
from .timezone import user_now, user_today, user_start_day

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_api_token)])
Db = Annotated[Session, Depends(get_db)]


@router.get("/dashboard")
def dashboard(db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    today = user_today(db, user_id)
    ids = [x.id for x in db.query(TelegramAccount).filter_by(user_id=user_id).all()]
    if not ids:
        return {
            "accounts": {"total": 0, "active": 0, "monitoring_on": 0},
            "cards": {
                "accounts": 0, "monitoring": 0, "viewed_today": 0,
                "in_queue": 0, "stories": 0, "skipped": 0, "errors": 0,
            },
            "charts": {
                "views_by_hour": [{"hour": h, "count": 0} for h in range(24)],
                "views_by_day": [
                    {"day": (today - timedelta(days=d)).date().isoformat(), "count": 0}
                    for d in range(13, -1, -1)
                ],
            },
            "recent": [],
        }

    recent = user_now(db, user_id) - timedelta(days=1)

    def c(model, *criteria):
        q = db.query(func.count(model.id)).filter(*criteria)
        return q.scalar() or 0

    # Card counts — single queries each.
    monitoring_count = (
        db.query(func.count(TelegramAccount.id))
        .filter(TelegramAccount.id.in_(ids), TelegramAccount.monitoring.is_(True))
        .scalar()
    )

    cards = {
        "accounts": len(ids),
        "monitoring": monitoring_count,
        "viewed_today": c(StoryView, StoryView.account_id.in_(ids), StoryView.viewed_at >= today),
        "in_queue": c(
            StoryQueue,
            StoryQueue.account_id.in_(ids),
            StoryQueue.status.in_(["PENDING", "WAITING_DELAY", "PROCESSING"]),
        ),
        "stories": c(Story, Story.account_id.in_(ids)),
        "skipped": c(
            ActivityLog,
            ActivityLog.account_id.in_(ids),
            ActivityLog.event_type == "story_skipped",
            ActivityLog.created_at >= recent,
        ),
        "errors": c(
            ActivityLog,
            ActivityLog.account_id.in_(ids),
            ActivityLog.level.in_(["ERROR", "CRITICAL"]),
            ActivityLog.created_at >= recent,
        ),
    }

    # --- Charts: single aggregated queries instead of 38 individual counts ---

    # Views by hour (today): use EXTRACT(HOUR) for a single query.
    hour_rows = (
        db.query(
            func.extract("hour", StoryView.viewed_at).label("hour"),
            func.count(StoryView.id).label("cnt"),
        )
        .filter(StoryView.account_id.in_(ids), StoryView.viewed_at >= today)
        .group_by(text("hour"))
        .all()
    )
    hour_map = {int(r.hour): r.cnt for r in hour_rows}
    views_by_hour = [{"hour": h, "count": hour_map.get(h, 0)} for h in range(24)]

    # Views by day (last 14 days): use DATE() aggregation.
    day_rows = (
        db.query(
            func.date(StoryView.viewed_at).label("day"),
            func.count(StoryView.id).label("cnt"),
        )
        .filter(
            StoryView.account_id.in_(ids),
            StoryView.viewed_at >= today - timedelta(days=13),
            StoryView.viewed_at < today + timedelta(days=1),
        )
        .group_by(text("day"))
        .all()
    )
    day_map = {str(r.day): r.cnt for r in day_rows}
    views_by_day = [
        {
            "day": (today - timedelta(days=d)).date().isoformat(),
            "count": day_map.get((today - timedelta(days=d)).date().isoformat(), 0),
        }
        for d in range(13, -1, -1)
    ]

    # Recent activity.
    recent_events = [
        {
            "id": x.id,
            "account_id": x.account_id,
            "event_type": x.event_type,
            "level": x.level,
            "message": x.message,
            "created_at": x.created_at,
        }
        for x in (
            db.query(ActivityLog)
            .filter(ActivityLog.account_id.in_(ids))
            .order_by(ActivityLog.created_at.desc())
            .limit(15)
        )
    ]

    return {
        "accounts": {"total": len(ids), "active": len(ids), "monitoring_on": monitoring_count},
        "cards": cards,
        "charts": {"views_by_hour": views_by_hour, "views_by_day": views_by_day},
        "recent": recent_events,
    }


@router.get("/stats")
def stats(db: Db, user_id: Annotated[int, Depends(current_user_id)], days: int = 7):
    today = user_today(db, user_id)
    start = user_start_day(db, user_id, days_ago=max(days - 1, 0))
    ids = [x.id for x in db.query(TelegramAccount.id).filter_by(user_id=user_id)]

    def count(model, *criteria):
        return db.query(func.count(model.id)).filter(*criteria).scalar() or 0

    views = count(StoryView, StoryView.account_id.in_(ids), StoryView.viewed_at >= start)
    likes = count(
        ActivityLog,
        ActivityLog.account_id.in_(ids),
        ActivityLog.event_type == "story_liked",
        ActivityLog.created_at >= start,
    )
    skipped = count(
        ActivityLog,
        ActivityLog.account_id.in_(ids),
        ActivityLog.event_type == "story_skipped",
        ActivityLog.created_at >= start,
    )
    errors = count(
        ActivityLog,
        ActivityLog.account_id.in_(ids),
        ActivityLog.level.in_(["ERROR", "CRITICAL"]),
        ActivityLog.created_at >= start,
    )
    found = count(Story, Story.account_id.in_(ids), Story.discovered_at >= start)

    # Daily views — aggregated.
    day_rows = (
        db.query(
            func.date(StoryView.viewed_at).label("day"),
            func.count(StoryView.id).label("cnt"),
        )
        .filter(
            StoryView.account_id.in_(ids),
            StoryView.viewed_at >= today - timedelta(days=max(days - 1, 0)),
            StoryView.viewed_at < today + timedelta(days=1),
        )
        .group_by(text("day"))
        .all()
    )
    day_map = {str(r.day): r.cnt for r in day_rows}
    daily = [
        {
            "day": (today - timedelta(days=d)).date().isoformat(),
            "count": day_map.get((today - timedelta(days=d)).date().isoformat(), 0),
        }
        for d in range(max(days - 1, 0), -1, -1)
    ]

    # Hourly views — aggregated.
    hour_rows = (
        db.query(
            func.extract("hour", StoryView.viewed_at).label("hour"),
            func.count(StoryView.id).label("cnt"),
        )
        .filter(StoryView.account_id.in_(ids), StoryView.viewed_at >= today)
        .group_by(text("hour"))
        .all()
    )
    hour_map = {int(r.hour): r.cnt for r in hour_rows}
    hourly = [{"hour": h, "count": hour_map.get(h, 0)} for h in range(24)]

    def source(model):
        return {
            k: v
            for k, v in db.query(model.source, func.count(model.id))
            .filter(
                (Story.account_id.in_(ids))
                if model is Story
                else (StoryView.account_id.in_(ids))
            )
            .group_by(model.source)
        }

    return {
        "period_days": days,
        "views_total": views,
        "likes_total": likes,
        "skipped_total": skipped,
        "errors_total": errors,
        "stories_found": found,
        "views_by_day": daily,
        "views_by_hour": hourly,
        "views_by_source": source(StoryView),
        "stories_by_source": source(Story),
        "queue_by_status": {
            k: v
            for k, v in db.query(StoryQueue.status, func.count(StoryQueue.id))
            .filter(StoryQueue.account_id.in_(ids))
            .group_by(StoryQueue.status)
        },
        "activity_by_type": {
            k: v
            for k, v in db.query(ActivityLog.event_type, func.count(ActivityLog.id))
            .filter(
                ActivityLog.account_id.in_(ids),
                ActivityLog.created_at >= start,
            )
            .group_by(ActivityLog.event_type)
        },
    }
