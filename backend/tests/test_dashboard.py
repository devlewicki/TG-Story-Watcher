"""Tests for the optimized /dashboard and /stats endpoints.

Verifies that aggregated SQL queries return correct data for cards,
charts, and stats.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class TestDashboard:
    """GET /dashboard"""

    def test_dashboard_structure(self, client, auth_headers, seed_accounts, seed_stories, seed_views, seed_activity):
        """Response has all expected top-level keys."""
        resp = client.get("/api/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "accounts" in data
        assert "cards" in data
        assert "charts" in data
        assert "recent" in data

    def test_account_counts(self, client, auth_headers, seed_accounts):
        resp = client.get("/api/dashboard", headers=auth_headers)
        data = resp.json()
        assert data["accounts"]["total"] == 2
        assert data["cards"]["accounts"] == 2
        assert data["accounts"]["monitoring_on"] == 2

    def test_cards_counts(self, client, auth_headers, seed_accounts, seed_stories, seed_views, seed_activity, seed_queue):
        resp = client.get("/api/dashboard", headers=auth_headers)
        data = resp.json()
        cards = data["cards"]
        # Stories count
        assert cards["stories"] == len(seed_stories)
        # Viewed today — at least the 10 we created
        assert cards["viewed_today"] >= 10
        # In queue — PENDING + WAITING_DELAY + PROCESSING = 3
        assert cards["in_queue"] == 3
        # Skipped — 5 story_skipped logs
        assert cards["skipped"] == 5
        # Errors — 2 ERROR logs
        assert cards["errors"] == 2

    def test_charts_views_by_hour(self, client, auth_headers, seed_accounts, seed_stories, seed_views):
        """views_by_hour should have 24 entries with non-negative counts."""
        resp = client.get("/api/dashboard", headers=auth_headers)
        data = resp.json()
        hours = data["charts"]["views_by_hour"]
        assert len(hours) == 24
        for h in hours:
            assert "hour" in h
            assert "count" in h
            assert h["count"] >= 0

    def test_charts_views_by_day(self, client, auth_headers, seed_accounts, seed_stories, seed_views):
        """views_by_day should have 14 entries (today + 13 previous days)."""
        resp = client.get("/api/dashboard", headers=auth_headers)
        data = resp.json()
        days = data["charts"]["views_by_day"]
        assert len(days) == 14
        for d in days:
            assert "day" in d
            assert "count" in d
            assert d["count"] >= 0

    def test_recent_activity(self, client, auth_headers, seed_accounts, seed_activity):
        """Recent activity should contain our logged events."""
        resp = client.get("/api/dashboard", headers=auth_headers)
        data = resp.json()
        recent = data["recent"]
        assert len(recent) > 0
        # Should include likes, skips, and errors
        event_types = {e["event_type"] for e in recent}
        assert "story_liked" in event_types
        assert "story_skipped" in event_types

    def test_empty_dashboard(self, client, auth_headers):
        """Dashboard returns zeros when no data."""
        resp = client.get("/api/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["accounts"]["total"] == 0
        assert data["cards"]["viewed_today"] == 0
        assert data["charts"]["views_by_hour"] == [{"hour": h, "count": 0} for h in range(24)]

    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 401


class TestStats:
    """GET /stats"""

    def test_stats_structure(self, client, auth_headers, seed_accounts, seed_stories, seed_views, seed_activity):
        resp = client.get("/api/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "views_total" in data
        assert "likes_total" in data
        assert "skipped_total" in data
        assert "errors_total" in data
        assert "views_by_day" in data
        assert "views_by_hour" in data
        assert "queue_by_status" in data
        assert "activity_by_type" in data

    def test_stats_totals(self, client, auth_headers, seed_accounts, seed_stories, seed_views, seed_activity):
        resp = client.get("/api/stats?days=7", headers=auth_headers)
        data = resp.json()
        # Views total — at least 10 from seed_views
        assert data["views_total"] >= 10
        # Likes total — 3 from seed_activity
        assert data["likes_total"] == 3
        # Skipped total — 5 from seed_activity
        assert data["skipped_total"] == 5
        # Errors total — 2 from seed_activity
        assert data["errors_total"] == 2

    def test_stats_charts_are_aggregated(self, client, auth_headers, seed_accounts, seed_stories, seed_views):
        """Stats charts should use aggregated queries (single query each)."""
        resp = client.get("/api/stats?days=7", headers=auth_headers)
        data = resp.json()
        assert len(data["views_by_hour"]) == 24
        assert len(data["views_by_day"]) >= 1

    def test_stats_period_days(self, client, auth_headers, seed_accounts):
        resp = client.get("/api/stats?days=30", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["period_days"] == 30
