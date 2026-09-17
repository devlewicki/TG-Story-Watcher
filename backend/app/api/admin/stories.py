"""Admin: global stories list with filters."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ...admin_auth import current_admin, require_admin_permission
from ...admin_models import AdminUser
from ...db import get_db
from ...models import Story, StoryQueue, StoryView, StoryViewer, TelegramAccount, User

router = APIRouter(tags=["admin-stories"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/stories")
def list_stories(
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    account_id: int | None = None,
    user_id: int | None = None,
    source: str | None = None,
    viewed: bool | None = None,
):
    q = db.query(Story)
    if account_id is not None:
        q = q.filter(Story.account_id == account_id)
    if user_id is not None:
        q = q.join(TelegramAccount, Story.account_id == TelegramAccount.id).filter(TelegramAccount.user_id == user_id)
    if source:
        q = q.filter(Story.source == source)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Story.author_username.ilike(like), Story.author_name.ilike(like)))
    if viewed is not None:
        viewed_story_ids = db.query(StoryView.story_id).filter(StoryView.status == "VIEWED")
        if viewed:
            q = q.filter(Story.id.in_(viewed_story_ids))
        else:
            q = q.filter(~Story.id.in_(viewed_story_ids))
    total = q.count()
    items = q.order_by(Story.discovered_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    story_ids = [s.id for s in items]
    view_rows = dict(
        db.query(StoryView.story_id, func.count(StoryView.id))
        .filter(StoryView.story_id.in_(story_ids or [-1]), StoryView.status == "VIEWED")
        .group_by(StoryView.story_id)
        .all()
    ) if story_ids else {}

    # Batch-load accounts + owners for the page (avoids N+1).
    account_ids = list({s.account_id for s in items})
    accounts = (
        db.query(TelegramAccount).filter(TelegramAccount.id.in_(account_ids or [-1])).all()
    )
    accounts_by_id = {a.id: a for a in accounts}
    owner_ids = list({a.user_id for a in accounts if a.user_id})
    owners = db.query(User).filter(User.id.in_(owner_ids or [-1])).all()
    owners_by_id = {u.id: u for u in owners}

    out = []
    for s in items:
        acc = accounts_by_id.get(s.account_id)
        owner_row = owners_by_id.get(acc.user_id) if acc and acc.user_id else None
        owner = {"id": owner_row.id, "email": owner_row.email} if owner_row else None
        out.append(
            {
                "id": s.id,
                "author_username": s.author_username,
                "author_name": s.author_name,
                "peer_id": s.peer_id,
                "telegram_story_id": s.telegram_story_id,
                "source": s.source,
                "published_at": s.published_at.isoformat() if s.published_at else None,
                "discovered_at": s.discovered_at.isoformat() if s.discovered_at else None,
                "account_id": s.account_id,
                "account_username": acc.username if acc else None,
                "owner": owner,
                "views": view_rows.get(s.id, 0),
            }
        )
    return {"total": total, "page": page, "page_size": page_size, "items": out}


@router.get("/stories/{story_id}")
def story_details(
    story_id: int,
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
):
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(404, "story not found")
    viewers = (
        db.query(StoryViewer).filter(StoryViewer.story_id == story_id)
        .order_by(StoryViewer.viewed_at.desc().nullslast())
        .limit(100)
        .all()
    )
    views = (
        db.query(StoryView).filter(StoryView.story_id == story_id)
        .order_by(StoryView.viewed_at.desc()).limit(20).all()
    )
    queue_items = db.query(StoryQueue).filter(StoryQueue.story_id == story_id).all()
    return {
        "id": story.id,
        "author_username": story.author_username,
        "author_name": story.author_name,
        "peer_id": story.peer_id,
        "telegram_story_id": story.telegram_story_id,
        "source": story.source,
        "published_at": story.published_at.isoformat() if story.published_at else None,
        "expires_at": story.expires_at.isoformat() if story.expires_at else None,
        "discovered_at": story.discovered_at.isoformat() if story.discovered_at else None,
        "account_id": story.account_id,
        "viewers_count": len(viewers),
        "viewers": [
            {
                "telegram_user_id": v.telegram_user_id,
                "username": v.username,
                "first_name": v.first_name,
                "viewed_at": v.viewed_at.isoformat() if v.viewed_at else None,
                "reaction": v.reaction,
            }
            for v in viewers
        ],
        "views": [
            {
                "account_id": v.account_id,
                "status": v.status,
                "viewed_at": v.viewed_at.isoformat() if v.viewed_at else None,
                "error": v.error,
            }
            for v in views
        ],
        "queue": [
            {"id": q.id, "status": q.status, "attempts": q.attempts, "error": q.error}
            for q in queue_items
        ],
    }
