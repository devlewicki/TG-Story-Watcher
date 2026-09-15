"""Admin authentication endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...admin_auth import (
    SESSION_TTL_HOURS,
    change_password,
    client_ip,
    create_admin_session,
    current_admin,
    ensure_bootstrap_admin,
)
from ...admin_models import AdminAuditLog, AdminSession, AdminUser
from ...db import get_db
from ...services import admin_audit

router = APIRouter(tags=["admin-auth"])

Db = Annotated[Session, Depends(get_db)]


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminPasswordChangeIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def _admin_out(admin: AdminUser) -> dict:
    return {
        "id": admin.id,
        "username": admin.username,
        "email": admin.email,
        "role": admin.role,
        "enabled": admin.enabled,
        "last_login_at": admin.last_login_at.isoformat() if admin.last_login_at else None,
    }


@router.post("/auth/login")
def admin_login(payload: AdminLoginIn, request: Request, db: Db):
    from ...multitenancy import verify_password

    ensure_bootstrap_admin(db)
    admin = db.query(AdminUser).filter(AdminUser.username == payload.username).first()
    if admin is None or not verify_password(payload.password, admin.password_hash):
        admin_audit.audit(
            admin_id=admin.id if admin else None,
            admin_username=payload.username,
            action="admin.login",
            result="FAILED",
            ip=client_ip(request),
        )
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    if not admin.enabled:
        raise HTTPException(status_code=403, detail="Admin account is disabled")
    token, _session = create_admin_session(
        db, admin, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    admin_audit.audit(
        admin_id=admin.id,
        admin_username=admin.username,
        action="admin.login",
        result="SUCCESS",
        ip=client_ip(request),
    )
    return {"token": token, "expires_in_hours": SESSION_TTL_HOURS, "admin": _admin_out(admin)}


@router.post("/auth/logout")
def admin_logout(
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
    db: Db,
):
    from datetime import datetime, timezone as _tz

    from ...admin_auth import admin_session_from_token

    session = admin_session_from_token(db, request.headers.get("x-admin-token"))
    if session is not None:
        session.revoked_at = datetime.now(_tz)
        db.commit()
    admin_audit.audit(
        admin_id=admin.id,
        admin_username=admin.username,
        action="admin.logout",
        ip=client_ip(request),
    )
    return {"ok": True}


@router.get("/auth/me")
def admin_me(admin: Annotated[AdminUser, Depends(current_admin)]):
    return _admin_out(admin)


@router.post("/auth/password")
def admin_change_password(
    payload: AdminPasswordChangeIn,
    request: Request,
    admin: Annotated[AdminUser, Depends(current_admin)],
    db: Db,
):
    ok = change_password(db, admin, payload.old_password, payload.new_password)
    admin_audit.audit(
        admin_id=admin.id,
        admin_username=admin.username,
        action="admin.password_change",
        result="SUCCESS" if ok else "FAILED",
        ip=client_ip(request),
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Wrong current password")
    return {"ok": True}


@router.get("/audit-logs")
def list_audit_logs(
    db: Db,
    admin: Annotated[AdminUser, Depends(current_admin)],
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
):
    page_size = min(max(page_size, 1), 200)
    q = db.query(AdminAuditLog)
    if action:
        q = q.filter(AdminAuditLog.action.ilike(f"%{action}%"))
    total = q.count()
    items = (
        q.order_by(AdminAuditLog.created_at.desc())
        .offset((max(page, 1) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": i.id,
                "admin_id": i.admin_id,
                "admin_username": i.admin_username,
                "action": i.action,
                "target": i.target,
                "result": i.result,
                "ip": i.ip,
                "error": i.error,
                "metadata": i.meta_json,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in items
        ],
    }
