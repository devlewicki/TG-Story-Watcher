"""Tests for discovery rotation offset isolation.

Verifies that the _location_offset dict is used separately from
_hashtag_offset, preventing key collisions.
"""
from __future__ import annotations

from app.workers.scheduler import _hashtag_offset, _location_offset, _auto_venue_offset, _geo_venue_offset


class TestRotationOffsets:
    """Verify offset dicts are isolated."""

    def test_location_offset_is_separate_dict(self):
        """_location_offset should be a separate dict from _hashtag_offset."""
        assert _location_offset is not _hashtag_offset

    def test_geo_venue_offset_is_separate_dict(self):
        """_geo_venue_offset should be a separate dict."""
        assert _geo_venue_offset is not _hashtag_offset
        assert _geo_venue_offset is not _location_offset

    def test_auto_venue_offset_is_separate_dict(self):
        """_auto_venue_offset should be a separate dict."""
        assert _auto_venue_offset is not _hashtag_offset
        assert _auto_venue_offset is not _location_offset

    def test_setting_location_offset_does_not_affect_hashtag(self):
        """Writing to _location_offset should not touch _hashtag_offset."""
        _location_offset[42] = 10
        assert 42 not in _hashtag_offset or _hashtag_offset.get(42) != 10
        # Cleanup
        _location_offset.pop(42, None)

    def test_setting_hashtag_offset_does_not_affect_location(self):
        """Writing to _hashtag_offset should not touch _location_offset."""
        _hashtag_offset[42] = 20
        assert 42 not in _location_offset or _location_offset.get(42) != 20
        # Cleanup
        _hashtag_offset.pop(42, None)
