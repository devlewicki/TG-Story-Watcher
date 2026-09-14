"""Tests for discovery flood-wait containment.

``stories.searchPosts`` is heavily rate-limited. If one venue/hashtag hits a
flood wait, we now remember the cooldown and abort the rest of the cycle
instead of sleeping ~30s per leftover entry.
"""
from __future__ import annotations

import asyncio
import types as py_types

from app.stories.discovery import (
    _flood_cooldown_until,
    _flood_pending,
    _remember_flood,
    search_hashtags,
    search_locations,
)


class _Account:
    id = 2001


class _Monitor:
    def __init__(self, client, db):
        self.client = client
        self.account = _Account()
        self.db = db


async def _noop_sleep(*a, **k):
    """Skip real flood-wait sleeps so the tests are fast."""
    return None


class _DB:
    def query(self, *a, **k):
        return _EmptyQuery()


class _EmptyQuery:
    def filter(self, *a, **k):
        return self

    def filter_by(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return None


class _RpcClient:
    """Calls a stub RPC; can be told to raise FloodWaitError part-way."""

    def __init__(self, fail_on_call: int | None = None, flood_seconds: int = 25):
        self.fail_on_call = fail_on_call
        self.flood_seconds = flood_seconds
        self.calls = 0
        self.requests: list[str] = []

    def is_connected(self) -> bool:
        return True

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        req = args[0] if args else None
        tag = getattr(req, "hashtag", None)
        self.requests.append(tag if tag is not None else "area")
        if self.fail_on_call is not None and self.calls >= self.fail_on_call:
            from telethon.errors import FloodWaitError
            raise FloodWaitError(None, self.flood_seconds)
        return py_types.SimpleNamespace(
            stories=[], users=[], chats=[], next_offset=None,
        )


def _make_flood_error(seconds: int = 25):
    from telethon.errors import FloodWaitError
    return FloodWaitError(None, seconds)


def test_flood_pending_defaults_false():
    assert _flood_pending(_Monitor(_RpcClient(), _DB())) is False


def test_remember_flood_sets_cooldown():
    mon = _Monitor(_RpcClient(), _DB())
    _remember_flood(mon, 60)
    try:
        assert _flood_pending(mon) is True
    finally:
        _flood_cooldown_until.pop(mon.account.id, None)


def test_search_hashtags_stops_after_flood():
    mon = _Monitor(_RpcClient(fail_on_call=2), _DB())
    _orig_sleep = asyncio.sleep
    asyncio.sleep = _noop_sleep
    try:
        result = asyncio.run(search_hashtags(mon, ["#alpha", "#beta", "#gamma"]))
    finally:
        asyncio.sleep = _orig_sleep

    try:
        # First tag searched, second floods -> remaining tags are NOT searched.
        assert result == 0
        assert mon.client.calls == 2
        assert mon.client.requests == ["alpha", "beta"]
        assert _flood_pending(mon) is True
    finally:
        _flood_cooldown_until.pop(mon.account.id, None)


def test_search_hashtags_respects_remembered_cooldown():
    mon = _Monitor(_RpcClient(), _DB())
    _remember_flood(mon, 60)
    try:
        result = asyncio.run(search_hashtags(mon, ["#alpha", "#beta"]))
        assert result == 0
        assert mon.client.calls == 0
    finally:
        _flood_cooldown_until.pop(mon.account.id, None)


def test_search_locations_stops_after_flood():
    mon = _Monitor(_RpcClient(fail_on_call=2), _DB())
    _orig_sleep = asyncio.sleep
    asyncio.sleep = _noop_sleep
    try:
        result = asyncio.run(
            search_locations(mon, ["city:volkhov", "venue:4c45d722", "venue:4c45d823"])
        )
    finally:
        asyncio.sleep = _orig_sleep

    try:
        assert result == 0
        assert mon.client.calls == 2
        assert _flood_pending(mon) is True
    finally:
        _flood_cooldown_until.pop(mon.account.id, None)


def test_search_locations_respects_remembered_cooldown():
    mon = _Monitor(_RpcClient(), _DB())
    _remember_flood(mon, 60)
    try:
        result = asyncio.run(search_locations(mon, ["venue:4c45d722"]))
        assert result == 0
        assert mon.client.calls == 0
    finally:
        _flood_cooldown_until.pop(mon.account.id, None)