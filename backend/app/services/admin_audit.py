"""Admin audit logging + system events. Never raises, never stores secrets."""
from __future__ import annotations

import json

from ..admin_models import AdminAuditLog, SystemEvent
from ..db import SessionLocal


def audit(
    *,
    admin_id: int | None,
    admin_username: str | None,
    action: str,
    target: str | None = None,
    result: str = "SUCCESS",
    ip: str | None = None,
    error: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Persist an admin audit log entry (never raises)."""
    try:
        db = SessionLocal()
        try:
            db.add(
                AdminAuditLog(
                    admin_id=admin_id,
                    admin_username=admin_username,
                    action=action[:128],
                    target=target[:255] if target else None,
                    result=result[:32],
                    ip=ip[:64] if ip else None,
                    error=(error or None) and str(error)[:2000],
                    meta_json=json.dumps(metadata, default=str) if metadata else None,
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001 audit must never throw
        pass


def system_event(
    component: str,
    event_type: str,
    message: str,
    *,
    severity: str = "INFO",
    metadata: dict | None = None,
) -> None:
    """Persist a global system event for the admin dashboard (never raises)."""
    try:
        db = SessionLocal()
        try:
            db.add(
                SystemEvent(
                    component=component[:64],
                    event_type=event_type[:64],
                    severity=severity[:16],
                    message=message[:2000],
                    meta_json=json.dumps(metadata, default=str) if metadata else None,
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        pass
