from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActivityLog, StoryView
from .deps import require_api_token
from .schemas import ActivityOut, ViewOut, activity_out

logger = logging.getLogger("storywatcher.api.history")

router = APIRouter(prefix="/history", tags=["history"], dependencies=[Depends(require_api_token)])

Db = Annotated[Session, Depends(get_db)]


def _view_out(v) -> dict:
    return {
        "id": v.id,
        "account_id": v.account_id,
        "peer_id": v.peer_id,
        "telegram_story_id": v.telegram_story_id,
        "story_id": v.story_id,
        "source": v.source,
        "rule_id": v.rule_id,
        "viewed_at": v.viewed_at,
        "status": v.status,
        "error": v.error,
    }


@router.get("/views/count")
def count_views(db: Db):
    return {"count": db.query(StoryView).count()}


@router.get("/activity/count")
def count_activity(db: Db):
    return {"count": db.query(ActivityLog).count()}


@router.get("/views", response_model=list[ViewOut])
def list_views(
    db: Db,
    account_id: int | None = None,
    peer_id: int | None = None,
    status: str | None = None,
    view_period: str | None = Query(default=None, alias="period"),
    limit: int = Query(200, le=1000),
    offset: int = 0,
):
    q = db.query(StoryView).order_by(StoryView.viewed_at.desc())
    if account_id is not None:
        q = q.filter(StoryView.account_id == account_id)
    if peer_id is not None:
        q = q.filter(StoryView.peer_id == peer_id)
    if status is not None:
        q = q.filter(StoryView.status == status)
    if view_period:
        if view_period == "today":
            start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            q = q.filter(StoryView.viewed_at >= start)
        elif view_period == "yesterday":
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            q = q.filter(
                StoryView.viewed_at >= today - timedelta(days=1),
                StoryView.viewed_at < today,
            )
        elif view_period == "week":
            q = q.filter(StoryView.viewed_at >= datetime.now(timezone.utc) - timedelta(days=7))
        elif view_period == "month":
            q = q.filter(StoryView.viewed_at >= datetime.now(timezone.utc) - timedelta(days=30))
    return [_view_out(v) for v in q.offset(offset).limit(limit).all()]


@router.get("/activity", response_model=list[ActivityOut])
def list_activity(
    db: Db,
    account_id: int | None = None,
    event_type: str | None = None,
    level: str | None = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
):
    q = db.query(ActivityLog).order_by(ActivityLog.created_at.desc())
    if account_id is not None:
        q = q.filter(ActivityLog.account_id == account_id)
    if event_type is not None:
        q = q.filter(ActivityLog.event_type == event_type)
    if level is not None:
        q = q.filter(ActivityLog.level == level.upper())
    return [activity_out(a) for a in q.offset(offset).limit(limit).all()]