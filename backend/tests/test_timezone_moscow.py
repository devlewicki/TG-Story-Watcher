"""Tests for the app-wide Moscow timezone policy.

The whole app (all users + admin) is pinned to Europe/Moscow; per-user
timezone settings are ignored. This file verifies the central helpers and
that the day boundaries they produce match Moscow midnight.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.api.timezone import (
    DEFAULT_TZ,
    user_now,
    user_start_day,
    user_today,
    user_tz_name,
)


def test_default_tz_is_moscow():
    assert DEFAULT_TZ == "Europe/Moscow"


def test_user_tz_name_ignores_stored_settings():
    # user_tz_name returns Moscow regardless of the (ignored) settings row.
    assert user_tz_name(None, 9999) == "Europe/Moscow"


def test_user_now_is_moscow_offset():
    with patch("app.api.timezone.datetime") as dt:
        dt.now.return_value = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        now = user_now(None, 1)
    assert now.utcoffset() == timedelta(hours=3)  # UTC 12:00 -> MSK 15:00 (+3)
    assert now.hour == 15


def test_user_today_maps_to_moscow_midnight_utc():
    # 2026-01-15 23:30 MSK is still Jan 15 -> midnight 2026-01-15 00:00 MSK,
    # which is 2026-01-14 21:00 UTC (Moscow is UTC+3, no DST).
    with patch("app.api.timezone.datetime") as dt:
        dt.now.return_value = datetime(2026, 1, 15, 20, 30, 0, tzinfo=timezone.utc)
        today = user_today(None, 1)
    assert today.tzinfo == timezone.utc
    assert today == datetime(2026, 1, 14, 21, 0, 0, tzinfo=timezone.utc)


def test_user_today_flips_at_moscow_midnight():
    # 2026-01-15 00:30 MSK == 2026-01-14 21:30 UTC -> already Jan 15 in Moscow.
    with patch("app.api.timezone.datetime") as dt:
        dt.now.return_value = datetime(2026, 1, 14, 21, 30, 0, tzinfo=timezone.utc)
        today = user_today(None, 1)
    assert today == datetime(2026, 1, 14, 21, 0, 0, tzinfo=timezone.utc)


def test_user_start_day_subtracts_days():
    with patch("app.api.timezone.datetime") as dt:
        dt.now.return_value = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        start = user_start_day(None, 1, days_ago=6)
    assert start == datetime(2026, 1, 8, 21, 0, 0, tzinfo=timezone.utc)


def test_user_today_consistent_with_now():
    with patch("app.api.timezone.datetime") as dt:
        dt.now.return_value = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        now = user_now(None, 1)
        today = user_today(None, 1)
    # Both come from the same mocked instant; today must be <= now and within
    # the same Moscow calendar day.
    assert today <= now
    assert (now - today) < timedelta(days=1)