"""Tests for discovery SearchPosts pacing and flood handling.

``stories.searchPosts`` is heavily rate-limited. The discovery path now:
  - spreads RPCs out via a per-account minimum interval;
  - caps how many SearchPosts run per account per cycle;
  - sleeps through the FIRST flood wait and keeps going, and only a second
    flood in the same cycle stops the list.
"""
from __future__ import annotations

import asyncio
import types as py_types

from app.stories.discovery import (
    SEARCH_POSTS_CYCLE_BUDGET,
    _reset_pacing,
    _search_rpc_cycle_budget,
    _flood_hits,
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
    """Calls a stub RPC; can be told to raise FloodWaitError on specific calls."""

    def __init__(self, flood_on_calls: set[int] | None = None, flood_seconds: int = 25):
        self.flood_on_calls = flood_on_calls or set()
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
        if self.calls in self.flood_on_calls:
            from telethon.errors import FloodWaitError
            raise FloodWaitError(None, self.flood_seconds)
        return py_types.SimpleNamespace(
            stories=[], users=[], chats=[], next_offset=None,
        )


def _reset(mon):
    _reset_pacing(mon)
    _search_rpc_cycle_budget.pop(mon.account.id, None)
    _flood_hits.pop(mon.account.id, None)


def test_budget_defaults_empty_when_uninitialized():
    mon = _Monitor(_RpcClient(), _DB())
    _search_rpc_cycle_budget.pop(mon.account.id, None)
    assert _search_rpc_cycle_budget.get(mon.account.id, 0) == 0


def test_search_hashtags_continues_after_first_flood():
    mon = _Monitor(_RpcClient(flood_on_calls={2}), _DB())
    _reset(mon)
    _orig_sleep = asyncio.sleep
    asyncio.sleep = _noop_sleep
    try:
        result = asyncio.run(search_hashtags(mon, ["#alpha", "#beta", "#gamma"]))
    finally:
        asyncio.sleep = _orig_sleep

    try:
        # First tag searched, second floods -> sleep and continue with the
        # third (only a SECOND flood in the same cycle stops the list).
        assert result == 0
        assert mon.client.calls == 3
        assert mon.client.requests == ["alpha", "beta", "gamma"]
        assert _flood_hits.get(mon.account.id) == 1
    finally:
        _reset(mon)


def test_search_hashtags_stops_after_second_flood():
    mon = _Monitor(_RpcClient(flood_on_calls={2, 3}), _DB())
    _reset(mon)
    _orig_sleep = asyncio.sleep
    asyncio.sleep = _noop_sleep
    try:
        result = asyncio.run(search_hashtags(mon, ["#alpha", "#beta", "#gamma", "#delta"]))
    finally:
        asyncio.sleep = _orig_sleep

    try:
        # alpha ok, beta floods (hit 1), gamma floods (hit 2 -> stop), delta skipped.
        assert result == 0
        assert mon.client.calls == 3
        assert mon.client.requests == ["alpha", "beta", "gamma"]
        assert _flood_hits.get(mon.account.id) == 2
    finally:
        _reset(mon)


def test_search_locations_continues_after_first_flood():
    mon = _Monitor(_RpcClient(flood_on_calls={2}), _DB())
    _reset(mon)
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
        assert mon.client.calls == 3
        assert _flood_hits.get(mon.account.id) == 1
    finally:
        _reset(mon)


def test_search_stops_when_budget_exhausted():
    mon = _Monitor(_RpcClient(), _DB())
    _reset(mon)
    _search_rpc_cycle_budget[mon.account.id] = 1
    _orig_sleep = asyncio.sleep
    asyncio.sleep = _noop_sleep
    try:
        result = asyncio.run(search_hashtags(mon, ["#a", "#b", "#c", "#d"]))
    finally:
        asyncio.sleep = _orig_sleep

    try:
        assert result == 0
        assert mon.client.calls == 1
    finally:
        _reset(mon)


def test_budget_refreshed_by_reset_pacing():
    mon = _Monitor(_RpcClient(), _DB())
    _reset(mon)
    _search_rpc_cycle_budget[mon.account.id] = 1
    _reset_pacing(mon)
    try:
        assert _search_rpc_cycle_budget[mon.account.id] == SEARCH_POSTS_CYCLE_BUDGET
    finally:
        _reset(mon)