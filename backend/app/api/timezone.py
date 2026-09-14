"""Timezone helpers — all time-based queries should use these.

The app is pinned to Moscow time for every user and the admin panel, so
per-user timezone settings are deliberately ignored (they were previously
read from ``general.timezone``).
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session

DEFAULT_TZ = "Europe/Moscow"


def _get_tz(_db: Session, _user_id: int) -> ZoneInfo:
    """Return the app-wide timezone (Moscow)."""
    return ZoneInfo(DEFAULT_TZ)


def user_now(_db: Session, _user_id: int) -> datetime:
    """Current time in Moscow (aware)."""
    return datetime.now(timezone.utc).astimezone(ZoneInfo(DEFAULT_TZ))


def user_today(_db: Session, _user_id: int) -> datetime:
    """Midnight today in Moscow, returned as UTC-aware datetime.

    This is the key function: it gives you the UTC instant that corresponds
    to 00:00 of the current day in Moscow time.
    """
    local_now = user_now(_db, _user_id)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)


def user_start_day(db: Session, user_id: int, days_ago: int = 0) -> datetime:
    """UTC-aware datetime for midnight N days ago in Moscow."""
    today = user_today(db, user_id)
    return today - timedelta(days=days_ago)


def user_tz_name(_db: Session, _user_id: int) -> str:
    """Return the app-wide timezone name (IANA), always Moscow.

    Used to pass to PostgreSQL ``AT TIME ZONE`` which natively supports
    IANA names, handling DST and fractional offsets automatically.
    """
    return DEFAULT_TZ
