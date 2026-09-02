"""Timezone helpers — all time-based queries should use these."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from ..services.settings_service import SettingsService

DEFAULT_TZ = "UTC"


def _get_tz(db: Session, user_id: int) -> ZoneInfo:
    """Return the user's configured timezone, fallback to UTC."""
    try:
        svc = SettingsService(db, user_id)
        tz_name = svc.get("general").get("timezone", DEFAULT_TZ) or DEFAULT_TZ
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def user_now(db: Session, user_id: int) -> datetime:
    """Current time in the user's timezone (aware)."""
    return datetime.now(timezone.utc).astimezone(_get_tz(db, user_id))


def user_today(db: Session, user_id: int) -> datetime:
    """Midnight today in the user's timezone, returned as UTC-aware datetime.

    This is the key function: it gives you the UTC instant that corresponds
    to 00:00 of the current day in the user's local time.
    """
    local_now = user_now(db, user_id)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)


def user_start_day(db: Session, user_id: int, days_ago: int = 0) -> datetime:
    """UTC-aware datetime for midnight N days ago in the user's timezone."""
    today = user_today(db, user_id)
    return today - timedelta(days=days_ago)
