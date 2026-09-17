"""Admin: global queue management."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...admin_auth import client_ip, current_admin, require_admin_permission
from ...admin_models import AdminUser
from ...db import get_db
from ...models import QueueStatus, Story, StoryQueue, TelegramAccount, User
from ...services import admin_audit

router = APIRouter(tags=["admin-queue"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/queue")
def list_queue(
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = None,
    account_id: int | None = None,
    user_id: int | None = None,
    search: str | None = None,
    min_retries: int | None = None,
):
    q = db.query(StoryQueue)
    if status:
        q = q.filter(StoryQueue.status == status)
    if account_id is not None:
        q = q.filter(StoryQueue.account_id == account_id)
    if user_id is not None:
        q = q.join(TelegramAccount, StoryQueue.account_id == TelegramAccount.id).filter(TelegramAccount.user_id == user_id)
    if min_retries is not None:
        q = q.filter(StoryQueue.attempts >= min_retries)
    if search:
        like = f"%{search}%"
        q = q.join(Story, StoryQueue.story_id == Story.id).filter(
            func.coalesce(Story.author_username, "").ilike(like)
        )
    total = q.count()
    items = (
        q.order_by(StoryQueue.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Batch-load stories + accounts for the page (StoryQueue has no ORM
    # relationships defined, so we join manually to avoid N+1).
    story_ids = list({i.story_id for i in items if i.story_id})
    stories = db.query(Story).filter(Story.id.in_(story_ids or [-1])).all()
    stories_by_id = {s.id: s for s in stories}
    account_ids = list({i.account_id for i in items})
    accounts = db.query(TelegramAccount).filter(TelegramAccount.id.in_(account_ids or [-1])).all()
    accounts_by_id = {a.id: a for a in accounts}
    owner_ids = list({a.user_id for a in accounts if a.user_id})
    owners = db.query(User).filter(User.id.in_(owner_ids or [-1])).all()
    owners_by_id = {u.id: u for u in owners}

    out = []
    for i in items:
        story = stories_by_id.get(i.story_id)
        acc = accounts_by_id.get(i.account_id)
        owner = owners_by_id.get(acc.user_id) if acc and acc.user_id else None
        out.append(
            {
                "id": i.id,
                "status": i.status,
                "priority": i.priority,
                "attempts": i.attempts,
                "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
                "started_at": i.started_at.isoformat() if i.started_at else None,
                "completed_at": i.completed_at.isoformat() if i.completed_at else None,
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "error": (i.error or "")[:300] or None,
                "story": {
                    "id": story.id if story else None,
                    "author_username": story.author_username if story else None,
                    "author_name": story.author_name if story else None,
                }
                if story
                else None,
                "account": {
                    "id": acc.id,
                    "username": acc.username,
                    "user_id": acc.user_id,
                    "owner_email": owner.email if owner else None,
                }
                if acc
                else None,
            }
        )
    return {"total": total, "page": page, "page_size": page_size, "items": out}


@router.get("/queue/health")
def queue_health(
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
):
    per_status = dict(
        db.query(StoryQueue.status, func.count(StoryQueue.id)).group_by(StoryQueue.status).all()
    )
    now = datetime.now(timezone.utc)
    stuck = (
        db.query(func.count(StoryQueue.id))
        .filter(
            StoryQueue.status == "PROCESSING",
            StoryQueue.started_at.isnot(None),
            StoryQueue.started_at < now - timedelta(minutes=30),
        )
        .scalar()
        or 0
    )
    oldest_pending = (
        db.query(func.min(StoryQueue.created_at))
        .filter(StoryQueue.status.in_(("PENDING", "WAITING_DELAY")))
        .scalar()
    )
    avg_time = (
        db.query(func.avg(func.extract("epoch", StoryQueue.completed_at - StoryQueue.started_at)))
        .filter(StoryQueue.status == "VIEWED", StoryQueue.completed_at.isnot(None), StoryQueue.started_at.isnot(None))
        .scalar()
    )
    return {
        "by_status": per_status,
        "active": sum(per_status.get(s, 0) for s in ("PENDING", "WAITING_DELAY", "PROCESSING")),
        "stuck": stuck,
        "failed": per_status.get("FAILED", 0),
        "oldest_pending": oldest_pending.isoformat() if oldest_pending else None,
        "avg_processing_seconds": round(avg_time, 1) if avg_time else None,
    }


@router.post("/queue/{item_id}/cancel")
def cancel_item(
    item_id: int,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    item = db.get(StoryQueue, item_id)
    if item is None:
        raise HTTPException(404, "queue item not found")
    if item.status not in ("VIEWED", "FAILED", "EXPIRED", "CANCELLED"):
        item.status = QueueStatus.CANCELLED.value
        item.completed_at = datetime.now(timezone.utc)
        db.commit()
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="queue.cancel",
        target=f"queue:{item_id}", ip=client_ip(request),
    )
    return {"ok": True, "status": item.status}


@router.post("/queue/{item_id}/retry")
def retry_item(
    item_id: int,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    item = db.get(StoryQueue, item_id)
    if item is None:
        raise HTTPException(404, "queue item not found")
    if item.status in ("VIEWED", "CANCELLED"):
        raise HTTPException(400, "item cannot be retried")
    item.status = QueueStatus.PENDING.value
    item.attempts = 0
    item.error = None
    item.completed_at = None
    item.scheduled_at = datetime.now(timezone.utc)
    db.commit()
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="queue.retry",
        target=f"queue:{item_id}", ip=client_ip(request),
    )
    return {"ok": True, "status": item.status}


@router.post("/queue/clear")
def clear_queue(
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
    scope: str = Query("finished", pattern="^(finished|failed|all)$"),
):
    """Clear finished (VIEWED/SKIPPED/EXPIRED/CANCELLED), failed, or everything."""
    statuses = {
        "finished": ("VIEWED", "SKIPPED", "EXPIRED", "CANCELLED"),
        "failed": ("FAILED",),
        "all": ("VIEWED", "SKIPPED", "EXPIRED", "CANCELLED", "FAILED", "PENDING", "WAITING_DELAY"),
    }[scope]
    changed = (
        db.query(StoryQueue)
        .filter(StoryQueue.status.in_(statuses))
        .delete(synchronize_session=False)
    )
    db.commit()
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="queue.clear",
        target=f"scope:{scope}", ip=client_ip(request), metadata={"deleted": changed},
    )
    return {"ok": True, "deleted": changed}


@router.post("/queue/reset-stuck")
def reset_stuck(
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
    minutes: int = Query(30, ge=1, le=720),
):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    changed = (
        db.query(StoryQueue)
        .filter(
            StoryQueue.status == "PROCESSING",
            StoryQueue.started_at.isnot(None),
            StoryQueue.started_at < cutoff,
        )
        .update(
            {
                StoryQueue.status: QueueStatus.PENDING.value,
                StoryQueue.started_at: None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="queue.reset_stuck",
        target=f"minutes:{minutes}", ip=client_ip(request), metadata={"reset": changed},
    )
    return {"ok": True, "reset": changed}
