"""Tests for SettingsService caching and compute_all_from_daily."""
from __future__ import annotations

import time

from app.services.settings_service import SettingsService, compute_all_from_daily


class TestComputeAllFromDaily:
    """compute_all_from_daily function tests."""

    def test_returns_all_sections(self):
        result = compute_all_from_daily(800)
        assert "limits" in result
        assert "view" in result
        assert "queue" in result
        assert "monitoring" in result

    def test_daily_limit_in_limits(self):
        result = compute_all_from_daily(800)
        assert result["limits"]["views_per_day"] == 800

    def test_views_per_hour_calculation(self):
        result = compute_all_from_daily(800)
        assert result["limits"]["views_per_hour"] == 800 // 24

    def test_views_per_minute_calculation(self):
        result = compute_all_from_daily(800)
        import math
        assert result["limits"]["views_per_minute"] == math.ceil(800 / 1440)

    def test_min_delay_greater_than_zero(self):
        result = compute_all_from_daily(800)
        assert result["view"]["min_delay"] > 0

    def test_max_delay_greater_than_min(self):
        result = compute_all_from_daily(800)
        assert result["view"]["max_delay"] >= result["view"]["min_delay"]

    def test_parallel_scales_with_daily(self):
        small = compute_all_from_daily(1000)
        large = compute_all_from_daily(8000)
        assert large["queue"]["parallel"] >= small["queue"]["parallel"]

    def test_daily_clamped_min(self):
        """Daily values below 50 are clamped to 50."""
        result = compute_all_from_daily(10)
        assert result["limits"]["views_per_day"] == 50

    def test_daily_clamped_max(self):
        """Daily values above 12000 are clamped to 12000."""
        result = compute_all_from_daily(20000)
        assert result["limits"]["views_per_day"] == 12000

    def test_caching_returns_same_result(self):
        """Same input should return the same output (cached)."""
        r1 = compute_all_from_daily(800)
        r2 = compute_all_from_daily(800)
        # LRU cache should return the exact same object
        assert r1 is r2

    def test_different_inputs_return_different_results(self):
        r1 = compute_all_from_daily(200)
        r2 = compute_all_from_daily(800)
        assert r1["limits"]["views_per_day"] != r2["limits"]["views_per_day"]


class TestSettingsServiceGet:
    """SettingsService.get() tests."""

    def test_get_defaults(self, db, user_id=42):
        svc = SettingsService(db, user_id)
        limits = svc.get("limits")
        assert "views_per_day" in limits
        assert limits["views_per_day"] == 800  # default

    def test_get_view_section(self, db, user_id=42):
        svc = SettingsService(db, user_id)
        view = svc.get("view")
        assert "min_delay" in view
        assert "max_delay" in view
        assert "auto_like" in view

    def test_get_queue_section(self, db, user_id=42):
        svc = SettingsService(db, user_id)
        queue = svc.get("queue")
        assert "max_tasks" in queue
        assert "parallel" in queue

    def test_set_and_get(self, db, user_id=42):
        svc = SettingsService(db, user_id)
        svc.set("view", {"auto_like": True, "like_emoji": "🔥"})
        result = svc.get("view")
        assert result["auto_like"] is True
        assert result["like_emoji"] == "🔥"

    def test_limits_recompute_on_set(self, db, user_id=42):
        """When views_per_day changes, derived values are recomputed."""
        svc = SettingsService(db, user_id)
        svc.set("limits", {"views_per_day": 2000})
        limits = svc.get("limits")
        assert limits["views_per_day"] == 2000
        assert limits["views_per_hour"] == 2000 // 24

    def test_get_all(self, db, user_id=42):
        svc = SettingsService(db, user_id)
        all_settings = svc.get_all()
        assert "general" in all_settings
        assert "limits" in all_settings
        assert "view" in all_settings
        assert "queue" in all_settings
        assert "discovery" in all_settings
        assert "filters" in all_settings
