"""Admin: global Telegram account management."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ...admin_auth import client_ip, current_admin, require_admin_permission
from ...admin_models import AdminUser
from ...db import get_db
from ...models import AccountStatus, StoryQueue, StoryView, TelegramAccount
from ...services import admin_audit

router = APIRouter(tags=["admin-accounts"])
Db = Annotated[Session, Depends(get_db)]


def _mask_phone(phone: str) -> str:
    """Show country code + last 2 digits only (secrets policy)."""
    digits = phone.lstrip("+")
    if len(digits) <= 4:
        return "+••••"
    return f"+{digits[:2]}••••{digits[-2:]}"


def _acc_row(db: Session, a: TelegramAccount, with_owner: bool = True) -> dict:
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    views_today = (
        db.query(func.count(StoryView.id)).filter(
            StoryView.account_id == a.id, StoryView.viewed_at >= day_ago
        ).scalar()
        or 0
    )
    queue_active = (
        db.query(func.count(StoryQueue.id)).filter(
            StoryQueue.account_id == a.id,
            StoryQueue.status.in_(("PENDING", "WAITING_DELAY", "PROCESSING")),
        ).scalar()
        or 0
    )
    owner = None
    if with_owner and a.user_id:
        from ...models import User

        owner_row = db.get(User, a.user_id)
        if owner_row:
            owner = {"id": owner_row.id, "email": owner_row.email, "name": f"{owner_row.first_name} {owner_row.last_name}"}
    return {
        "id": a.id,
        "phone_masked": _mask_phone(a.phone),
        "telegram_user_id": a.telegram_user_id,
        "username": a.username,
        "first_name": a.first_name,
        "last_name": a.last_name,
        "status": a.status,
        "monitoring": a.monitoring,
        "views_today": views_today,
        "queue_active": queue_active,
        "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None,
        "has_session": bool(a.session_path),
        "owner": owner,
    }


@router.get("/accounts")
def list_accounts(
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    status: str | None = None,
    user_id: int | None = None,
):
    q = db.query(TelegramAccount)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                TelegramAccount.username.ilike(like),
                TelegramAccount.first_name.ilike(like),
                TelegramAccount.last_name.ilike(like),
                TelegramAccount.phone.ilike(like),
            )
        )
    if status:
        q = q.filter(TelegramAccount.status == status)
    if user_id is not None:
        q = q.filter(TelegramAccount.user_id == user_id)
    total = q.count()
    items = q.order_by(TelegramAccount.id).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [_acc_row(db, a) for a in items]}


@router.get("/accounts/{account_id}")
def account_details(
    account_id: int,
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
):
    acc = db.get(TelegramAccount, account_id)
    if acc is None:
        raise HTTPException(404, "account not found")
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    views_today = (
        db.query(func.count(StoryView.id)).filter(
            StoryView.account_id == acc.id, StoryView.viewed_at >= day_ago
        ).scalar() or 0
    )
    last_view = (
        db.query(StoryView).filter(StoryView.account_id == acc.id)
        .order_by(StoryView.viewed_at.desc()).first()
    )
    from ...models import StoryQueue as SQ

    queue_by_status = dict(
        db.query(SQ.status, func.count(SQ.id)).filter(SQ.account_id == acc.id).group_by(SQ.status).all()
    )
    return {
        **_acc_row(db, acc),
        "phone": _mask_phone(acc.phone),  # never full phone
        "views_today": views_today,
        "queue_by_status": queue_by_status,
        "last_view_at": last_view.viewed_at.isoformat() if last_view else None,
        # Secrets policy: never expose api_hash, session contents, proxy secret.
        "api_configured": bool(acc.api_id and acc.api_hash),
    }


@router.post("/accounts/{account_id}/start")
async def start_account(
    account_id: int,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    """Admin start: mirrors user API start (existing lifecycle)."""
    acc = db.get(TelegramAccount, account_id)
    if acc is None:
        raise HTTPException(404, "account not found")
    acc.monitoring = True
    if acc.status in (AccountStatus.PAUSED.value, AccountStatus.ERROR.value, AccountStatus.DISCONNECTED.value):
        acc.status = AccountStatus.ACTIVE.value
    db.commit()
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="account.start",
        target=f"account:{account_id}", ip=client_ip(request),
    )
    return {"ok": True, "status": acc.status, "monitoring": acc.monitoring}


@router.post("/accounts/{account_id}/pause")
async def pause_account(
    account_id: int,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    acc = db.get(TelegramAccount, account_id)
    if acc is None:
        raise HTTPException(404, "account not found")
    acc.status = AccountStatus.PAUSED.value
    acc.monitoring = False
    db.commit()
    try:
        from ...telegram import client_manager as cm

        await cm.drop_client(account_id)
    except Exception:  # noqa: BLE001
        pass
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="account.pause",
        target=f"account:{account_id}", ip=client_ip(request),
    )
    return {"ok": True, "status": acc.status, "monitoring": acc.monitoring}


@router.post("/accounts/{account_id}/reconnect")
async def reconnect_account(
    account_id: int,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    acc = db.get(TelegramAccount, account_id)
    if acc is None:
        raise HTTPException(404, "account not found")
    try:
        from ...telegram import client_manager as cm

        await cm.drop_client(account_id)
        if acc.session_path:
            await cm.connect(acc)
    except Exception as exc:  # noqa: BLE001
        admin_audit.audit(
            admin_id=admin.id, admin_username=admin.username, action="account.reconnect",
            target=f"account:{account_id}", result="FAILED", ip=client_ip(request), error=str(exc),
        )
        raise HTTPException(502, f"reconnect failed: {exc}")
    acc.status = AccountStatus.ACTIVE.value
    db.commit()
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="account.reconnect",
        target=f"account:{account_id}", ip=client_ip(request),
    )
    return {"ok": True, "status": acc.status}


@router.delete("/accounts/{account_id}")
async def remove_account(
    account_id: int,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    """Remove account row + session file (destructive, audited)."""
    acc = db.get(TelegramAccount, account_id)
    if acc is None:
        raise HTTPException(404, "account not found")
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="account.remove",
        target=f"account:{account_id}", ip=client_ip(request),
        metadata={"username": acc.username, "owner_id": acc.user_id},
    )
    try:
        from ...telegram import client_manager as cm

        await cm.drop_client(account_id)
    except Exception:  # noqa: BLE001
        pass
    import os

    if acc.session_path and os.path.isfile(acc.session_path):
        try:
            os.remove(acc.session_path)
        except OSError:
            pass
    db.delete(acc)
    db.commit()
    return {"ok": True}
