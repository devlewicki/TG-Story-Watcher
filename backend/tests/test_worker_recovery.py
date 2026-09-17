"""Tests for worker queue recovery semantics.

Covers the restart-recycling bug: ``_recover_stale_processing`` and the
``_requeue`` path in the worker must consume one retry per recovery so a batch
orphaned by repeated worker restarts is not recycled forever.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Story, StoryQueue, TelegramAccount
from app.workers.queue_worker import _recover_stale_processing


def _seed(db):
    acc = TelegramAccount(user_id=42, phone="79990007777", status="ACTIVE", monitoring=True)
    db.add(acc)
    db.flush()
    story = Story(account_id=acc.id, peer_id=5001, telegram_story_id=9001)
    db.add(story)
    db.flush()
    db.commit()
    return acc.id


def _queue_item(db, account_id, *, status="PROCESSING", started_at, attempts, error=None):
    item = StoryQueue(
        account_id=account_id,
        story_id=db.query(Story).filter_by(account_id=account_id).first().id,
        status=status,
        attempts=attempts,
        started_at=started_at,
        scheduled_at=datetime.now(timezone.utc),
        error=error,
    )
    db.add(item)
    db.commit()
    return item


def test_recover_stale_processing_requeues_and_increments_attempts(db):
    account_id = _seed(db)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    item = _queue_item(db, account_id, started_at=old, attempts=0)

    recovered = _recover_stale_processing(db, account_id, timeout_s=300, max_retries=3)

    assert recovered == 1
    db.refresh(item)
    assert item.status == "PENDING"
    assert item.started_at is None
    assert item.attempts == 1


def test_recover_stale_processing_stops_at_retry_cap(db):
    account_id = _seed(db)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    item = _queue_item(db, account_id, started_at=old, attempts=3)

    recovered = _recover_stale_processing(db, account_id, timeout_s=300, max_retries=3)

    assert recovered == 0
    db.refresh(item)
    assert item.status == "PROCESSING"
    assert item.attempts == 3


def test_recover_stale_processing_does_not_recycle_same_batch_forever(db):
    account_id = _seed(db)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    item = _queue_item(db, account_id, started_at=old, attempts=0)

    # Simulate repeated crash cycles: item claimed (PROCESSING) -> worker dies
    # -> recovery requeues it. Each round consumes one retry.
    for _ in range(3):
        item.status = "PROCESSING"
        item.started_at = old
        db.commit()
        _recover_stale_processing(db, account_id, timeout_s=300, max_retries=3)

    db.refresh(item)
    assert item.attempts == 3

    # Retry budget spent: further recovery sweeps leave the item alone.
    assert _recover_stale_processing(db, account_id, timeout_s=300, max_retries=3) == 0
    db.refresh(item)
    assert item.attempts == 3


def test_recover_stale_processing_skips_recent_items(db):
    account_id = _seed(db)
    fresh = datetime.now(timezone.utc)  # still within the processing timeout
    item = _queue_item(db, account_id, started_at=fresh, attempts=0)

    recovered = _recover_stale_processing(db, account_id, timeout_s=300, max_retries=3)

    assert recovered == 0
    db.refresh(item)
    assert item.status == "PROCESSING"