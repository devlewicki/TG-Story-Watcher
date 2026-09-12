"""Admin: user management."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ...admin_auth import client_ip, current_admin, require_admin_permission
from ...admin_models import AdminUser
from ...db import get_db
from ...models import (
    ActivityLog,
    AutomationRule,
    Story,
    StoryQueue,
    StoryView,
    TelegramAccount,
    User,
)
from ...services import admin_audit
from ...multitenancy import revoke_user_tokens

router = APIRouter(tags=["admin-users"])
Db = Annotated[Session, Depends(get_db)]


def _user_row(db: Session, u: User) -> dict:
    accounts = db.query(func.count(TelegramAccount.id)).filter(TelegramAccount.user_id == u.id).scalar() or 0
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    views_today = (
        db.query(func.count(StoryView.id))
        .join(TelegramAccount, StoryView.account_id == TelegramAccount.id)
        .filter(TelegramAccount.user_id == u.id, StoryView.viewed_at >= day_ago)
        .scalar()
        or 0
    )
    queue_active = (
        db.query(func.count(StoryQueue.id))
        .join(TelegramAccount, StoryQueue.account_id == TelegramAccount.id)
        .filter(TelegramAccount.user_id == u.id, StoryQueue.status.in_(("PENDING", "WAITING_DELAY", "PROCESSING")))
        .scalar()
        or 0
    )
    last_activity = (
        db.query(ActivityLog.created_at)
        .join(TelegramAccount, ActivityLog.account_id == TelegramAccount.id)
        .filter(TelegramAccount.user_id == u.id)
        .order_by(ActivityLog.created_at.desc())
        .first()
    )
    blocked = bool(
        db.query(func.count(TelegramAccount.id)).filter(
            TelegramAccount.user_id == u.id, TelegramAccount.monitoring.is_(True)
        ).scalar()
        == 0
        and accounts > 0
    )
    return {
        "id": u.id,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "email": u.email,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "accounts": accounts,
        "views_today": views_today,
        "queue_active": queue_active,
        "last_activity": last_activity[0].isoformat() if last_activity else None,
        "blocked": blocked,
    }


@router.get("/users")
def list_users(
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    filter: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
):
    q = db.query(User)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(User.email.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like)))
    if filter == "no_accounts":
        q = q.filter(~User.id.in_(db.query(TelegramAccount.user_id).filter(TelegramAccount.user_id.isnot(None))))
    if filter == "blocked":
        q = q.filter(
            User.id.in_(
                db.query(TelegramAccount.user_id).filter(TelegramAccount.user_id.isnot(None)).except_(
                    db.query(TelegramAccount.user_id).filter(TelegramAccount.monitoring.is_(True))
                )
            )
        )
    sort_col = {
        "created_at": User.created_at,
        "email": User.email,
        "id": User.id,
    }.get(sort, User.created_at)
    q = q.order_by(sort_col.desc() if order == "desc" else sort_col.asc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_user_row(db, u) for u in items],
    }


@router.get("/users/{user_id}")
def user_details(
    user_id: int,
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    accounts = db.query(TelegramAccount).filter(TelegramAccount.user_id == user_id).all()
    acc_ids = [a.id for a in accounts]
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    views_today = (
        db.query(func.count(StoryView.id)).filter(
            StoryView.account_id.in_(acc_ids or [-1]), StoryView.viewed_at >= day_ago
        ).scalar()
        or 0
    )
    queue_by_status = dict(
        db.query(StoryQueue.status, func.count(StoryQueue.id))
        .filter(StoryQueue.account_id.in_(acc_ids or [-1]))
        .group_by(StoryQueue.status)
        .all()
    )
    stories_total = db.query(func.count(Story.id)).filter(Story.account_id.in_(acc_ids or [-1])).scalar() or 0
    rules = db.query(AutomationRule).filter(AutomationRule.account_id.in_(acc_ids or [-1])).count()
    activity = (
        db.query(ActivityLog)
        .filter(ActivityLog.account_id.in_(acc_ids or [-1]))
        .order_by(ActivityLog.created_at.desc())
        .limit(20)
        .all()
    )
    return {
        **_user_row(db, user),
        "accounts": [
            {
                "id": a.id,
                "phone": a.phone,
                "username": a.username,
                "status": a.status,
                "monitoring": a.monitoring,
            }
            for a in accounts
        ],
        "views_today": views_today,
        "stories": stories_total,
        "rules": rules,
        "queue_by_status": queue_by_status,
        "activity": [
            {
                "id": l.id,
                "event_type": l.event_type,
                "level": l.level,
                "message": l.message,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in activity
        ],
    }


class UserBlockIn(BaseModel):
    blocked: bool


@router.post("/users/{user_id}/block")
def block_user(
    user_id: int,
    payload: UserBlockIn,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    """Block = disable monitoring on all user's accounts; unblock re-enables."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    accounts = db.query(TelegramAccount).filter(TelegramAccount.user_id == user_id).all()
    for acc in accounts:
        acc.monitoring = not payload.blocked
    if payload.blocked:
        revoke_user_tokens(user_id)
    db.commit()
    admin_audit.audit(
        admin_id=admin.id,
        admin_username=admin.username,
        action="user.block" if payload.blocked else "user.unblock",
        target=f"user:{user_id}",
        ip=client_ip(request),
    )
    return {"ok": True}


@router.post("/users/{user_id}/logout-all")
def logout_user(
    user_id: int,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    if db.get(User, user_id) is None:
        raise HTTPException(404, "user not found")
    revoke_user_tokens(user_id)
    admin_audit.audit(
        admin_id=admin.id,
        admin_username=admin.username,
        action="user.logout_all",
        target=f"user:{user_id}",
        ip=client_ip(request),
    )
    return {"ok": True}


@router.post("/users/{user_id}/clear-queue")
def clear_user_queue(
    user_id: int,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    acc_ids = [
        row[0]
        for row in db.query(TelegramAccount.id).filter(TelegramAccount.user_id == user_id).all()
    ]
    changed = (
        db.query(StoryQueue)
        .filter(
            StoryQueue.account_id.in_(acc_ids or [-1]),
            StoryQueue.status.in_(("PENDING", "WAITING_DELAY")),
        )
        .update(
            {StoryQueue.status: "CANCELLED", StoryQueue.completed_at: datetime.now(timezone.utc)},
            synchronize_session=False,
        )
    )
    db.commit()
    admin_audit.audit(
        admin_id=admin.id,
        admin_username=admin.username,
        action="user.clear_queue",
        target=f"user:{user_id}",
        ip=client_ip(request),
        metadata={"cancelled": changed},
    )
    return {"ok": True, "cancelled": changed}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    admin_audit.audit(
        admin_id=admin.id,
        admin_username=admin.username,
        action="user.delete",
        target=f"user:{user_id}",
        ip=client_ip(request),
        metadata={"email": user.email},
    )
    db.delete(user)  # CASCADE removes accounts, stories, queue...
    db.commit()
    return {"ok": True}
