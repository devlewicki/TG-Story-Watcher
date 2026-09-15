"""Admin authentication and RBAC.

Separate from user auth: admin tokens are opaque random strings stored in the
``admin_sessions`` table (server-side sessions), never user HMAC tokens.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .admin_models import AdminRole, AdminSession, AdminUser
from .db import get_db
from .multitenancy import hash_password, verify_password

SESSION_TTL_HOURS = 12

Db = Session


def _hash_token(token: str) -> str:
    """Store only a SHA-256 digest of the session token in the DB."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_admin_session(
    db: Session,
    admin: AdminUser,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, AdminSession]:
    token = "adm." + secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    session = AdminSession(
        id=secrets.token_hex(16),
        admin_id=admin.id,
        token=_hash_token(token),
        ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:512] or None,
        created_at=now,
        last_activity_at=now,
        expires_at=now + timedelta(hours=SESSION_TTL_HOURS),
    )
    db.add(session)
    admin.last_login_at = now
    db.commit()
    db.refresh(session)
    return token, session


def _utc(value: datetime) -> datetime:
    """Coerce a DB datetime to timezone-aware UTC (SQLite returns naive)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def admin_session_from_token(db: Session, token: str | None) -> AdminSession | None:
    if not token:
        return None
    row = (
        db.query(AdminSession)
        .filter(AdminSession.token == _hash_token(token))
        .first()
    )
    if row is None or row.revoked_at is not None:
        return None
    now = datetime.now(timezone.utc)
    if _utc(row.expires_at) <= now:
        return None
    # Sliding expiration: touch last activity and extend TTL while active.
    row.last_activity_at = now
    row.expires_at = now + timedelta(hours=SESSION_TTL_HOURS)
    db.commit()
    return row


def current_admin(
    x_admin_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AdminUser:
    session = admin_session_from_token(db, x_admin_token)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin authentication required")
    admin = db.get(AdminUser, session.admin_id)
    if admin is None or not admin.enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin account disabled")
    # Expose session for audit logging in endpoints.
    admin.current_session = session  # type: ignore[attr-defined]
    return admin


def require_admin_permission(write: bool):
    """Dependency factory: READ_ONLY role may only perform GET requests."""

    def _dep(
        request: Request,
        admin: AdminUser = Depends(current_admin),
    ) -> AdminUser:
        role = admin.role
        if role == AdminRole.SUPER_ADMIN.value:
            return admin
        if role == AdminRole.ADMIN.value and not write:
            return admin
        if role == AdminRole.ADMIN.value and write and request.method in ("GET", "HEAD"):
            return admin
        if role == AdminRole.READ_ONLY.value and request.method in ("GET", "HEAD") and not write:
            return admin
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin permissions")

    return _dep


def require_super_admin(admin: AdminUser = Depends(current_admin)) -> AdminUser:
    if admin.role != AdminRole.SUPER_ADMIN.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super admin permission required")
    return admin


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def ensure_bootstrap_admin(db: Session) -> None:
    """Create the initial SUPER_ADMIN if no admin exists.

    The password comes from ``ADMIN_BOOTSTRAP_PASSWORD`` (or a generated one
    printed to server logs on first start).
    """
    import logging
    import os

    if db.query(AdminUser).count() > 0:
        return
    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD") or secrets.token_urlsafe(16)
    admin = AdminUser(
        username=os.environ.get("ADMIN_BOOTSTRAP_USERNAME") or "admin",
        email=None,
        password_hash=hash_password(password),
        role=AdminRole.SUPER_ADMIN.value,
        enabled=True,
    )
    db.add(admin)
    db.commit()
    if not os.environ.get("ADMIN_BOOTSTRAP_PASSWORD"):
        logging.getLogger("storywatcher.admin").warning(
            "Bootstrap admin created: username=admin password=%s (set ADMIN_BOOTSTRAP_PASSWORD to control this)",
            password,
        )


def change_password(db: Session, admin: AdminUser, old: str, new: str) -> bool:
    if not verify_password(old, admin.password_hash):
        return False
    admin.password_hash = hash_password(new)
    db.commit()
    return True
