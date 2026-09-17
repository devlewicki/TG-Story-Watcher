"""Tests for discovery early-exit when the Telegram client disconnects.

A VPN-level disconnect (``VpnMonitor.shutdown_all``) drops every client.  The
discovery loops used to keep issuing ``SearchPosts`` requests that all failed
with "Cannot send requests while disconnected", wasting the whole cycle's
budget.  Now each search boundary checks ``client.is_connected()`` and aborts
immediately, so no Telegram RPC is attempted once the client is gone.
"""
from __future__ import annotations

import asyncio
import types as py_types

from app.stories.discovery import _connected, search_hashtags, search_locations


class _Client:
    def __init__(self, connected: bool):
        self.connected = connected
        self.calls = 0

    def is_connected(self) -> bool:
        return self.connected


class _Account:
    id = 1001


class _Monitor:
    def __init__(self, client, db):
        self.client = client
        self.account = _Account()
        self.db = db


class _DB:
    """Minimal stand-in so activity.log never touches a real session."""

    def query(self, *a, **k):
        return _EmptyQuery()


class _EmptyQuery:
    def filter(self, *a, **k):
        return self

    def first(self):
        return None


async def _fake_rpc(*a, **k):
    raise AssertionError("no Telegram RPC should be attempted while disconnected")


class _RpcClient:
    """Real callable client with an optional stub RPC."""

    def __init__(self, connected: bool, callback=None):
        self.connected = connected
        self._callback = callback
        self.calls = 0

    def is_connected(self) -> bool:
        return self.connected

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        if self._callback is None:
            raise AssertionError("no Telegram RPC should be attempted while disconnected")
        return await self._callback(*args, **kwargs)


def test_connected_helper_detects_disconnect():
    assert _connected(_Monitor(_Client(True), _DB())) is True
    assert _connected(_Monitor(_Client(False), _DB())) is False


def test_search_hashtags_aborts_when_disconnected():
    mon = _Monitor(_RpcClient(False), _DB())
    result = asyncio.run(search_hashtags(mon, ["#one", "#two"]))

    assert result == 0
    assert mon.client.calls == 0


def test_search_locations_aborts_when_disconnected():
    mon = _Monitor(_RpcClient(False), _DB())
    result = asyncio.run(search_locations(mon, ["city:volkhov", "venue:4c45d7"]))

    assert result == 0
    assert mon.client.calls == 0


def test_connected_client_makes_execute_calls():
    async def _rpc(*a, **k):
        return py_types.SimpleNamespace(
            stories=[], users=[], chats=[], next_offset=None,
        )

    mon = _Monitor(_RpcClient(True, _rpc), _DB())
    result = asyncio.run(search_hashtags(mon, ["#one"]))

    # Connected client: the RPC is invoked once; zero stories means 0 processed.
    assert mon.client.calls == 1
    assert result == 0