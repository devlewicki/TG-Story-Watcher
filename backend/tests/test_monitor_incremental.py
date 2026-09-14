"""Tests for incremental ``stories.getAllStories`` state handling.

Covers the change that makes the burst sync resume from a persisted Telegram
state (so unchanged cycles fetch nothing instead of re-ingesting the whole
feed) and only write a ``fetch_available`` activity entry when something was
actually processed.
"""
from __future__ import annotations

import asyncio
import types as py_types
from datetime import datetime, timedelta, timezone

import pytest

from app.models import ActivityLog, SettingsStore, Story, TelegramAccount, User
from app.stories import monitor as mon


@pytest.fixture()
def account(db):
    uid = 42
    if db.get(User, uid) is None:
        db.add(User(id=uid, first_name="T", last_name="U", email="t@t.t", password_hash="x"))
        db.commit()
    acc = TelegramAccount(
        id=1001, user_id=uid, phone="+110011", status="ACTIVE",
        monitoring=True, session_path="/tmp/monitor.session",
    )
    db.add(acc)
    db.commit()
    return acc


def _story_item(peer_id: int, story_id: int):
    """A flat story-like item the parser accepts."""
    return py_types.SimpleNamespace(
        id=story_id,
        date=datetime.now(timezone.utc),
        expire_date=datetime.now(timezone.utc) + timedelta(hours=12),
        peer_id=peer_id,
    )


class FakeClient:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    async def __call__(self, request, *args, **kwargs):
        self.calls.append(request)
        if not self._responses:
            raise RuntimeError("no more responses for GetAllStoriesRequest")
        return self._responses.pop(0)

    async def get_entity(self, peer_ids):
        if not isinstance(peer_ids, (list, set, tuple)):
            peer_ids = [peer_ids]
        out = []
        for pid in peer_ids:
            uid = pid.user_id if isinstance(pid, py_types.SimpleNamespace) and hasattr(pid, "user_id") else pid
            out.append(py_types.SimpleNamespace(user_id=uid, username=f"u{uid}", first_name="F", last_name="L"))
        return out


def _all_stories(state: str | None, peers: dict[int, list[int]], has_more=False):
    peer_stories = []
    for pid, ids in peers.items():
        peer_stories.append(
            py_types.SimpleNamespace(
                peer=py_types.SimpleNamespace(user_id=pid),
                stories=[_story_item(pid, sid) for sid in ids],
            )
        )
    return py_types.SimpleNamespace(
        state=state, peer_stories=peer_stories,
        users=[], chats=[], has_more=has_more,
        stories=None,
    )


def _not_modified(state: str):
    return py_types.SimpleNamespace(state=state, stealth_mode=py_types.SimpleNamespace())


def _mk_monitor(client, account, db):
    m = mon.StoryMonitor(client, account, db)
    # Unknown users pass the default filter (include_unknown=True), so stories
    # from unseeded peers get verdict "enqueued"/"already" rather than skipped.
    return m


def test_full_resync_persists_state(db, account):
    client = FakeClient([_all_stories("abc123", {11: [1, 2]})])
    m = _mk_monitor(client, account, db)

    result = asyncio.run(m.fetch_available(resync=True))

    # A real story was ingested, so it counted as processed.
    assert result >= 1
    # The returned state hash was persisted.
    row = db.get(SettingsStore, f"account:{account.id}:allstories_state")
    assert row is not None and row.value == "abc123"
    # Full (non-Hidden) feed was requested without a prior state.
    req = client.calls[0]
    assert getattr(req, "next", None) is False


def test_incremental_uses_stored_state(db, account):
    db.add(SettingsStore(key=f"account:{account.id}:allstories_state", value="abc123", updated_at=datetime.now(timezone.utc)))
    db.commit()
    client = FakeClient([_all_stories("xyz789", {})])
    m = _mk_monitor(client, account, db)

    asyncio.run(m.fetch_available())

    req = client.calls[0]
    assert req.state == "abc123"
    # Fresh state from the response is persisted for the next cycle.
    row = db.get(SettingsStore, f"account:{account.id}:allstories_state")
    assert row is not None and row.value == "xyz789"


def test_not_modified_keeps_state_and_skips_log(db, account):
    db.add(SettingsStore(key=f"account:{account.id}:allstories_state", value="abc123", updated_at=datetime.now(timezone.utc)))
    db.commit()
    client = FakeClient([_not_modified("abc123")])
    m = _mk_monitor(client, account, db)

    result = asyncio.run(m.fetch_available())

    assert result == 0
    assert db.query(ActivityLog).filter_by(event_type="fetch_available").count() == 0
    # State remains saved (NotModified returns the same hash).
    row = db.get(SettingsStore, f"account:{account.id}:allstories_state")
    assert row is not None and row.value == "abc123"


def test_stale_state_forces_full_resync(db, account):
    db.add(SettingsStore(key=f"account:{account.id}:allstories_state", value="abc123", updated_at=datetime.now(timezone.utc) - timedelta(hours=12)))
    db.commit()
    client = FakeClient([_not_modified("zzz999")])
    m = _mk_monitor(client, account, db)

    asyncio.run(m.fetch_available())

    req = client.calls[0]
    assert req.state is None
    assert db.get(SettingsStore, f"account:{account.id}:allstories_state").value == "zzz999"


def test_returned_state_kept_on_not_modified(db, account):
    """A fresh feed (with stories) refreshes the stored state."""
    client = FakeClient([_all_stories("state-v2", {11: [5, 6]})])
    m = _mk_monitor(client, account, db)

    asyncio.run(m.fetch_available(resync=True))

    row = db.get(SettingsStore, f"account:{account.id}:allstories_state")
    assert row.value == "state-v2"


def test_activity_log_only_when_processed(db, account):
    # First run: real stories -> log entry.
    client = FakeClient([_all_stories("s1", {11: [1]})])
    m = _mk_monitor(client, account, db)
    asyncio.run(m.fetch_available(resync=True))
    assert db.query(ActivityLog).filter_by(event_type="fetch_available").count() == 1

    # Second cycle: nothing new -> no log entry even though the monitor runs.
    s2 = FakeClient([_not_modified("s1")])
    m2 = _mk_monitor(s2, account, db)
    asyncio.run(m2.fetch_available())
    assert db.query(ActivityLog).filter_by(event_type="fetch_available").count() == 1