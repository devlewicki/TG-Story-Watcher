"""Tests for the optimized /stories list endpoint.

Verifies that DB-level pagination, sorting, view counts, and like
annotations all return correct data.
"""
from __future__ import annotations

import json


class TestStoriesList:
    """GET /stories"""

    def test_returns_stories(self, client, auth_headers, seed_stories, seed_views, seed_activity):
        resp = client.get("/api/stories", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_viewed_stories_sorted_first(self, client, auth_headers, seed_stories, seed_views):
        """Stories with views should appear before unviewed stories."""
        resp = client.get("/api/stories", headers=auth_headers)
        data = resp.json()
        # Find the boundary: first story without last_viewed_at
        first_unviewed_idx = None
        for i, s in enumerate(data):
            if s["last_viewed_at"] is None:
                first_unviewed_idx = i
                break
        if first_unviewed_idx is not None:
            # All stories before this index should have views
            for s in data[:first_unviewed_idx]:
                assert s["last_viewed_at"] is not None

    def test_view_count_aggregation(self, client, auth_headers, seed_stories, seed_views):
        """Story 0 was viewed from its owning account (view_count >= 1)."""
        resp = client.get("/api/stories", headers=auth_headers)
        data = resp.json()
        story0 = next((s for s in data if s["id"] == seed_stories[0].id), None)
        assert story0 is not None
        # view_count reflects views from the story's owning account only
        assert story0["view_count"] >= 1

    def test_like_annotation(self, client, auth_headers, seed_stories, seed_activity):
        """Stories 0, 1, 2 should have likes."""
        resp = client.get("/api/stories", headers=auth_headers)
        data = resp.json()
        # Data items are dicts, check for 'liked' key
        liked_ids = {s["id"] for s in data if isinstance(s, dict) and s.get("liked")}
        # Stories 0, 1, 2 should be liked
        assert seed_stories[0].id in liked_ids
        assert seed_stories[1].id in liked_ids
        assert seed_stories[2].id in liked_ids

    def test_pagination_offset_limit(self, client, auth_headers, seed_stories, seed_views):
        """Offset and limit work correctly."""
        resp1 = client.get("/api/stories?limit=5&offset=0", headers=auth_headers)
        resp2 = client.get("/api/stories?limit=5&offset=5", headers=auth_headers)
        data1 = resp1.json()
        data2 = resp2.json()
        assert len(data1) <= 5
        assert len(data2) <= 5
        # Different stories (no overlap)
        ids1 = {s["id"] for s in data1}
        ids2 = {s["id"] for s in data2}
        assert ids1.isdisjoint(ids2)

    def test_filter_by_source(self, client, auth_headers, seed_stories, seed_views):
        """Filtering by source works."""
        resp = client.get("/api/stories?source=analytics", headers=auth_headers)
        data = resp.json()
        for s in data:
            assert s["source"] == "analytics"

    def test_filter_by_peer_id(self, client, auth_headers, seed_stories, seed_views):
        """Filtering by peer_id works."""
        target_peer = seed_stories[0].peer_id
        resp = client.get(f"/api/stories?peer_id={target_peer}", headers=auth_headers)
        data = resp.json()
        for s in data:
            assert s["peer_id"] == target_peer

    def test_filter_by_account_id(self, client, auth_headers, seed_stories, seed_views):
        """Filtering by account_id works."""
        target_acc = seed_stories[0].account_id
        resp = client.get(f"/api/stories?account_id={target_acc}", headers=auth_headers)
        data = resp.json()
        for s in data:
            assert s["account_id"] == target_acc

    def test_empty_result_with_no_stories(self, client, auth_headers):
        """Empty result when no stories exist."""
        resp = client.get("/api/stories", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/api/stories")
        assert resp.status_code == 401


class TestStoriesCount:
    """GET /stories/count"""

    def test_count_matches(self, client, auth_headers, seed_stories):
        resp = client.get("/api/stories/count", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == len(seed_stories)


class TestStoriesGetOne:
    """GET /stories/{id}"""

    def test_get_existing_story(self, client, auth_headers, seed_stories):
        sid = seed_stories[0].id
        resp = client.get(f"/api/stories/{sid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == sid

    def test_get_nonexistent_returns_404(self, client, auth_headers):
        resp = client.get("/api/stories/999999", headers=auth_headers)
        assert resp.status_code == 404
