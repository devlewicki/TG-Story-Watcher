from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ActivityLog, Story, StoryQueue, StoryView, TelegramAccount
from ..services.settings_service import SettingsService
from .deps import require_api_token, current_user_id
from .schemas import QueueItemOut, StoryOut, story_out

logger = logging.getLogger("storywatcher.api.stories")

router = APIRouter(tags=["stories"], dependencies=[Depends(require_api_token)])

Db = Annotated[Session, Depends(get_db)]


@router.get("/stories", response_model=list[StoryOut])
def list_stories(
    db: Db,
    user_id: Annotated[int, Depends(current_user_id)],
    account_id: int | None = None,
    peer_id: int | None = None,
    source: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    from sqlalchemy import func, case

    # Subquery: last view time and view count per story.
    views_sub = (
        db.query(
            StoryView.account_id,
            StoryView.peer_id,
            StoryView.telegram_story_id,
            func.max(StoryView.viewed_at).label("last_viewed_at"),
            func.count(StoryView.id).label("view_count"),
        )
        .group_by(StoryView.account_id, StoryView.peer_id, StoryView.telegram_story_id)
        .subquery()
    )

    q = (
        db.query(Story)
        .join(TelegramAccount, Story.account_id == TelegramAccount.id)
        .filter(TelegramAccount.user_id == user_id)
    )
    if account_id is not None:
        q = q.filter(Story.account_id == account_id)
    if peer_id is not None:
        q = q.filter(Story.peer_id == peer_id)
    if source is not None:
        q = q.filter(Story.source == source)

    # We need the total count for the frontend pagination display.
    # But we must NOT load all stories — apply DB-level sort + pagination.
    # Sort: viewed stories first (by last_viewed_at desc), then unviewed (by discovered_at desc).
    # This requires a LEFT JOIN + COALESCE for the sort expression.
    q_with_views = (
        q.outerjoin(views_sub,
            (Story.account_id == views_sub.c.account_id)
            & (Story.peer_id == views_sub.c.peer_id)
            & (Story.telegram_story_id == views_sub.c.telegram_story_id)
        )
    )

    # Build sort expression: viewed stories first, then by most-recent time.
    view_indicator = case(
        (views_sub.c.last_viewed_at.isnot(None), 1),
        else_=0,
    )
    sort_time = func.coalesce(
        views_sub.c.last_viewed_at,
        Story.discovered_at,
        Story.published_at,
        datetime(1970, 1, 1, tzinfo=timezone.utc),
    )

    stories_with_views = (
        q_with_views
        .add_columns(
            views_sub.c.last_viewed_at,
            func.coalesce(views_sub.c.view_count, 0),
        )
        .order_by(view_indicator.desc(), sort_time.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Unpack ORM object + joined aggregate columns (no extra query needed).
    stories = [sv[0] for sv in stories_with_views]
    EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
    views_map: dict[tuple[int, int, int], tuple[datetime, int]] = {}
    for s, last, cnt in stories_with_views:
        views_map[(s.account_id, s.peer_id, s.telegram_story_id)] = (last, cnt)

    # Batch-load likes for returned stories — query by account_id + event_type
    # (both indexed) and parse meta_json in Python, replacing the old LIKE-on-
    # JSON scan that could not use any index.
    liked: dict[tuple[int, int], str] = {}
    story_account_ids = list({s.account_id for s in stories})
    if story_account_ids:
        for a in (
            db.query(ActivityLog)
            .filter(
                ActivityLog.event_type == "story_liked",
                ActivityLog.account_id.in_(story_account_ids),
            )
            .order_by(ActivityLog.created_at.desc())
            .limit(5000)
            .all()
        ):
            try:
                meta = json.loads(a.meta_json) if a.meta_json else {}
            except (ValueError, TypeError):
                continue
            pid = meta.get("peer_id")
            sid = meta.get("story_id")
            if pid is not None and sid is not None:
                liked.setdefault((int(pid), int(sid)), meta.get("emoji") or "👍")

    out = []
    for s in stories:
        emoji = liked.get((s.peer_id, s.telegram_story_id))
        last_view, cnt = views_map.get(
            (s.account_id, s.peer_id, s.telegram_story_id), (None, 0)
        )
        out.append(
            story_out(
                s,
                liked=emoji is not None,
                like_emoji=emoji,
                last_viewed_at=last_view,
                view_count=cnt,
            )
        )
    return out


@router.get("/stories/count")
def count_stories(db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    """Total number of stored stories for the current user."""
    return {"count": db.query(Story).join(TelegramAccount).filter(TelegramAccount.user_id == user_id).count()}


@router.get("/stories/{story_id}", response_model=StoryOut)
def get_story(story_id: int, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    s = db.query(Story).join(TelegramAccount).filter(Story.id == story_id, TelegramAccount.user_id == user_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="story not found")
    return story_out(s)


@router.post("/stories/{story_id}/view", response_model=QueueItemOut)
def view_story(story_id: int, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    s = db.query(Story).join(TelegramAccount).filter(Story.id == story_id, TelegramAccount.user_id == user_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="story not found")
    existing = (
        db.query(StoryQueue)
        .filter_by(account_id=s.account_id, story_id=s.id)
        .filter(StoryQueue.status.notin_(["CANCELLED"]))
        .first()
    )
    if existing is not None:
        return QueueItemOut(**(item_dict(existing, s)))
    import random

    svc = SettingsService(db, user_id)
    min_d = int(svc.get("view").get("min_delay", 0))
    max_d = max(int(svc.get("view").get("max_delay", 10)), min_d)
    delay = random.randint(min_d, max_d)
    item = StoryQueue(
        account_id=s.account_id,
        story_id=s.id,
        status="PENDING",
        scheduled_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return QueueItemOut(**(item_dict(item, s)))


@router.post("/stories/{story_id}/skip")
def skip_story(story_id: int, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    s = db.query(Story).join(TelegramAccount).filter(Story.id == story_id, TelegramAccount.user_id == user_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="story not found")
    item = db.query(StoryQueue).filter_by(account_id=s.account_id, story_id=s.id).first()
    if item is not None and item.status not in ("VIEWED", "FAILED", "EXPIRED", "SKIPPED"):
        item.status = "SKIPPED"
        if item.completed_at is None:
            item.completed_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True, "story_id": story_id}


def item_dict(q: StoryQueue, s: Story) -> dict:
    from .schemas import QueueItemOut

    return {
        "id": q.id,
        "account_id": q.account_id,
        "story_id": q.story_id,
        "status": q.status,
        "priority": q.priority,
        "scheduled_at": q.scheduled_at,
        "started_at": q.started_at,
        "completed_at": q.completed_at,
        "attempts": q.attempts,
        "error": q.error,
        "created_at": q.created_at,
        "story": story_out(s),
    }