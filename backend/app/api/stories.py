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
    q = db.query(Story).join(TelegramAccount, Story.account_id == TelegramAccount.id).filter(TelegramAccount.user_id == user_id)
    if account_id is not None:
        q = q.filter(Story.account_id == account_id)
    if peer_id is not None:
        q = q.filter(Story.peer_id == peer_id)
    if source is not None:
        q = q.filter(Story.source == source)
    # Fetch the whole (small) table: sorting by last-view time and pagination
    # happen in Python below, so truncating here would silently drop the newest
    # stories and make offset pagination run out early.
    stories = q.all()

    # Annotate which stories received an automatic like (from the activity log).
    liked: dict[tuple[int, int], str] = {}
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.event_type == "story_liked")
        .order_by(ActivityLog.created_at.desc())
        .limit(5000)
        .all()
    )
    for a in logs:
        try:
            meta = json.loads(a.meta_json) if a.meta_json else {}
        except (ValueError, TypeError):
            continue
        pid = meta.get("peer_id")
        sid = meta.get("story_id")
        if pid is not None and sid is not None:
            liked.setdefault((int(pid), int(sid)), meta.get("emoji") or "👍")

    # Last view time & view count per story (account_id, peer_id, telegram_story_id).
    EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
    views_map: dict[tuple[int, int, int], tuple[datetime, int]] = {}
    for sv in db.query(StoryView).all():  # small table for MVP
        k = (sv.account_id, sv.peer_id, sv.telegram_story_id)
        last, cnt = views_map.get(k, (None, 0))
        if last is None or sv.viewed_at > last:
            last = sv.viewed_at
        views_map[k] = (last, cnt + 1)

    def sort_key(s: Story):
        v = views_map.get((s.account_id, s.peer_id, s.telegram_story_id))
        if v is not None and v[0] is not None:
            # Viewed stories first, newest view on top.
            return (1, int(v[0].timestamp()))
        # Unviewed stories below, ordered by discovery / publish time.
        discovered = (s.discovered_at or EPOCH).timestamp()
        published = (s.published_at or EPOCH).timestamp()
        return (0, max(discovered, published))

    stories.sort(key=sort_key, reverse=True)
    stories = stories[offset : offset + limit]

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
    if item is not None:
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