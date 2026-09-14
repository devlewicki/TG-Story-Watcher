"""Tests for worker queue-drain resilience around failed DB sessions.

A web/admin process may change or delete a ``story_queue`` row between the
worker's load and flush.  That used to surface as ``StaleDataError`` during a
commit, then ``PendingRollbackError`` while writing the ERROR status — which
cascaded into a worker cycle error.  Now a stale row is a benign race (roll
back, drop the drain, keep the account un-touched), and any other drain failure
rolls back the session before persisting the ERROR status.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm.exc import StaleDataError

from app.models import Story, StoryQueue, TelegramAccount
from app.workers import queue_worker as qw


def _seed_account(db):
    acc = TelegramAccount(
        user_id=42, phone="79990007700", status="ACTIVE", monitoring=True,
        session_path="/tmp/resilience.session",
    )
    db.add(acc)
    db.flush()
    story = Story(account_id=acc.id, peer_id=6001, telegram_story_id=91001)
    db.add(story)
    db.flush()
    db.commit()
    return acc.id


def _queue_item(db, account_id):
    item = StoryQueue(
        account_id=account_id,
        story_id=db.query(Story).filter_by(account_id=account_id).first().id,
        status="PENDING",
        attempts=0,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.add(item)
    db.commit()
    return item


def test_stale_data_error_is_benign_race(db):
    account_id = _seed_account(db)
    _queue_item(db, account_id)
    account = db.get(TelegramAccount, account_id)

    async def _boom(db, account):
        raise StaleDataError("UPDATE story_queue ... affected 0 rows")

    with patch.object(qw, "drain_queue", new=_boom), patch.object(qw, "cm") as cm_mock:
        result = asyncio.run(qw._drain_account(db, account))

    assert result == 0
    # Account must NOT be flagged ERROR by a plain concurrency race.
    assert db.get(TelegramAccount, account_id).status == "ACTIVE"
    cm_mock.drop_client.assert_not_called()
    cm_mock.reconnect.assert_not_called()


def test_generic_failure_after_pending_rollback_persists_error(db):
    account_id = _seed_account(db)
    _queue_item(db, account_id)

    async def _boom(db, account):
        # Simulate a real failure that left the session in a failed state.
        db.rollback()
        raise RuntimeError("something exploded")

    with patch.object(qw, "drain_queue", new=_boom):
        account = db.get(TelegramAccount, account_id)
        result = asyncio.run(qw._drain_account(db, account))

    assert result == 0
    # The ERROR status is persisted via a fresh transaction (rollback first).
    assert db.get(TelegramAccount, account_id).status == "ERROR"


def test_recover_stale_processing_rolls_back_on_commit_failure(db):
    account_id = _seed_account(db)
    item = _queue_item(db, account_id)
    item.status = "PROCESSING"
    item.started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()

    # Force the commit inside _recover_stale_processing to fail.
    import sqlalchemy.orm.session as _sess_mod
    orig_commit = _sess_mod.Session.commit

    def _failing_commit(self, *args, **kwargs):
        orig_commit(self, *args, **kwargs)
        raise StaleDataError("boom on commit")

    with patch.object(_sess_mod.Session, "commit", new=_failing_commit):
        recovered = qw._recover_stale_processing(db, account_id, timeout_s=300, max_retries=3)

    assert recovered == 1
    # The session is usable after the rollback inside the helper.
    assert db.get(StoryQueue, item.id) is not None