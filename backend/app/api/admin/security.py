"""Admin: security — admin sessions management."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ...admin_auth import client_ip, current_admin, require_super_admin
from ...admin_models import AdminSession, AdminUser
from ...db import get_db
from ...services import admin_audit

router = APIRouter(tags=["admin-security"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/security/sessions")
def list_sessions(
    db: Db,
    _admin: Annotated[AdminUser, Depends(current_admin)],
):
    rows = (
        db.query(AdminSession, AdminUser.username)
        .join(AdminUser, AdminSession.admin_id == AdminUser.id)
        .filter(AdminSession.revoked_at.is_(None))
        .order_by(AdminSession.last_activity_at.desc())
        .limit(200)
        .all()
    )
    now = datetime.now(timezone.utc)
    return {
        "items": [
            {
                "id": s.id,
                "admin_username": username,
                "ip": s.ip,
                "user_agent": s.user_agent,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "last_activity_at": s.last_activity_at.isoformat() if s.last_activity_at else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "expired": s.expires_at <= now,
            }
            for s, username in rows
        ]
    }


@router.post("/security/sessions/{session_id}/revoke")
def revoke_session(
    session_id: str,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_super_admin)],
):
    session = db.get(AdminSession, session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    admin_audit.audit(
        admin_id=admin.id,
        admin_username=admin.username,
        action="security.session_revoke",
        target=f"session:{session_id}",
        ip=client_ip(request),
    )
    return {"ok": True}


@router.post("/security/sessions/revoke-all")
def revoke_all_sessions(
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_super_admin)],
):
    now = datetime.now(timezone.utc)
    changed = (
        db.query(AdminSession)
        .filter(AdminSession.revoked_at.is_(None))
        .update({AdminSession.revoked_at: now}, synchronize_session=False)
    )
    db.commit()
    admin_audit.audit(
        admin_id=admin.id,
        admin_username=admin.username,
        action="security.session_revoke_all",
        ip=client_ip(request),
        metadata={"revoked": changed},
    )
    return {"ok": True, "revoked": changed}
