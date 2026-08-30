from __future__ import annotations

import json

from ..db import SessionLocal
from ..models import ActivityLog


def log(
    message: str,
    *,
    event_type: str = "event",
    level: str = "INFO",
    account_id: int | None = None,
    metadata: dict | None = None,
    db=None,
) -> None:
    """Persist an activity log entry (never raises)."""
    try:
        session = db or SessionLocal()
        try:
            entry = ActivityLog(
                account_id=account_id,
                event_type=event_type,
                level=level,
                message=message,
                meta_json=json.dumps(metadata, default=str) if metadata else None,
            )
            session.add(entry)
            session.commit()
        finally:
            if db is None:
                session.close()
    except Exception:  # noqa: BLE001  logging must never throw
        pass


def recent(db, limit: int = 50, account_id: int | None = None):
    q = db.query(ActivityLog)
    if account_id is not None:
        q = q.filter(ActivityLog.account_id == account_id)
    return q.order_by(ActivityLog.created_at.desc()).limit(limit).all()