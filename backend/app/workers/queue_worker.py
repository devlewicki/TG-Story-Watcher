"""
Background worker that drains the story-view queue with per-account rate limits.

The worker runs in its own process (the ``worker`` compose service), polls for
due queue items, and invokes :func:`app.queue.processor.process_queue_item` on
each. A companion scheduler (``app.workers.scheduler``) drives the periodic
fetch of available stories.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from ..db import SessionLocal
from ..models import (
    AccountStatus,
    StoryQueue,
    StoryView,
    TelegramAccount,
)
from ..queue.processor import process_queue_item
from ..services import activity
from ..services.settings_service import SettingsService
from ..telegram import client_manager as cm

logger = logging.getLogger("storywatcher.worker")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RateLimiter:
    """Sliding-window counter per account per window (minute/hour/day)."""

    def __init__(self, db: Session):
        self.db = db

    def count_today(self, account_id: int) -> int:
        start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        return (
            self.db.query(func.count(StoryView.id))
            .filter(StoryView.account_id == account_id, StoryView.viewed_at >= start)
            .scalar()
            or 0
        )

    def count_since(self, account_id: int, seconds: int) -> int:
        since = _now() - timedelta(seconds=seconds)
        return (
            self.db.query(func.count(StoryView.id))
            .filter(StoryView.account_id == account_id, StoryView.viewed_at >= since)
            .scalar()
            or 0
        )


def _recover_stale_processing(
    db: Session, account_id: int, timeout_s: int, max_retries: int
) -> int:
    """Reset PROCESSING items that have been in-flight too long back to PENDING.

    A crashed/killed worker leaves its in-flight items stuck in PROCESSING
    forever: ``_due_items`` only selects PENDING/WAITING_DELAY, so nothing ever
    picks them up again. Requeue the stale ones so they get processed on the
    next sweep. Items that already exhausted ``max_retries`` are left alone for
    manual review (retry via the queue API).
    """
    cutoff = _now() - timedelta(seconds=timeout_s)
    stale = (
        db.query(StoryQueue)
        .filter(
            StoryQueue.account_id == account_id,
            StoryQueue.status == "PROCESSING",
            or_(StoryQueue.started_at.is_(None), StoryQueue.started_at < cutoff),
            StoryQueue.attempts < max_retries,
        )
        .all()
    )
    for item in stale:
        logger.warning(
            "auto-recovering stale PROCESSING item %s (started=%s, attempts=%s)",
            item.id,
            item.started_at,
            item.attempts,
        )
        item.status = "PENDING"
        item.started_at = None
        item.completed_at = None
        item.error = None
        item.scheduled_at = _now()
    if stale:
        db.commit()
    return len(stale)


def _due_items(db: Session, account_id: int, max_items: int) -> Sequence[StoryQueue]:
    return (
        db.query(StoryQueue)
        .options(joinedload(StoryQueue.story))
        .filter(
            StoryQueue.account_id == account_id,
            StoryQueue.status.in_(["PENDING", "WAITING_DELAY"]),
            StoryQueue.scheduled_at <= _now(),
        )
        .order_by(StoryQueue.priority.desc(), StoryQueue.scheduled_at.asc())
        .limit(max_items)
        .all()
    )


async def drain_queue(db: Session, account: TelegramAccount) -> None:
    """Process all currently-due queue entries for a single account."""
    client = await cm.connect(account)
    if not client.is_connected():
        return

    if not await client.is_user_authorized():
        account.status = AccountStatus.AUTH_REQUIRED.value
        db.commit()
        return

    svc = SettingsService(db)
    limits = svc.get("limits")
    per_min = int(limits.get("views_per_minute", 10))
    per_hour = int(limits.get("views_per_hour", 200))
    per_day = int(limits.get("views_per_day", 1500))
    parallel = max(int(svc.get("queue").get("parallel", 1)), 1)

    limiter = RateLimiter(db)

    # Enforce per-day budget first.
    if limiter.count_today(account.id) >= per_day:
        logger.info("account %s at daily view limit (%d)", account.id, per_day)
        account.status = AccountStatus.PAUSED.value
        db.commit()
        return

    # Recover items stuck in PROCESSING from a crashed/killed worker run so
    # they don't block the queue forever.
    qcfg = svc.get("queue")
    _recover_stale_processing(
        db,
        account.id,
        timeout_s=int(qcfg.get("processing_timeout", 300)),
        max_retries=int(qcfg.get("max_auto_retries", 3)),
    )

    items = _due_items(db, account.id, max_items=int(qcfg.get("max_tasks", 25)))
    if not items:
        return

    semaphore = asyncio.Semaphore(parallel)
    results = []

    async def _handle(item: StoryQueue):
        async with semaphore:
            # Sliding-window guards before each view.
            if limiter.count_since(account.id, 60) >= per_min:
                await asyncio.sleep(5)
            if limiter.count_since(account.id, 3600) >= per_hour:
                account.status = AccountStatus.FLOOD_WAIT.value
                db.commit()
                return {"item": item.id, "status": "LIMIT"}

            res = await process_queue_item(client, account, item, db)
            results.append(res)
            await asyncio.sleep(0.3)  # small delay between views

    await asyncio.gather(*(_handle(i) for i in items))

    # If any FloodWait was hit, back off before the next sweep.
    flood = [r for r in results if isinstance(r, dict) and r.get("flood_wait")]
    if flood:
        account.status = AccountStatus.FLOOD_WAIT.value
        worst = max(r["flood_wait"] for r in flood)
        db.commit()
        logger.warning("account %s flood wait for %ss", account.id, worst)
        await asyncio.sleep(min(worst, 60))
    elif account.status in (AccountStatus.ACTIVE.value,):
        account.status = AccountStatus.ACTIVE.value
        db.commit()


async def run_once() -> int:
    """Single worker sweep across all accounts. Returns number of processed items."""
    db = SessionLocal()
    total = 0
    try:
        accounts = (
            db.query(TelegramAccount)
            .filter(TelegramAccount.monitoring.is_(True))
            .all()
        )
        for account in accounts:
            if account.status in (
                AccountStatus.AUTH_REQUIRED.value,
                AccountStatus.BANNED_OR_RESTRICTED.value,
            ):
                continue
            try:
                await drain_queue(db, account)
                # drain_queue may legitimately leave the account limited
                # (daily budget exhausted -> PAUSED, hourly budget / flood wait
                # -> FLOOD_WAIT). Don't overwrite those states back to ACTIVE.
                if account.status not in (
                    AccountStatus.PAUSED.value,
                    AccountStatus.FLOOD_WAIT.value,
                    AccountStatus.AUTH_REQUIRED.value,
                    AccountStatus.BANNED_OR_RESTRICTED.value,
                ):
                    account.status = AccountStatus.ACTIVE.value
                db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.error("drain_queue(%s) failed: %s", account.id, exc)
                account.status = AccountStatus.ERROR.value
                activity.log(
                    f"worker drain failed: {exc}",
                    event_type="worker_error",
                    level="ERROR",
                    account_id=account.id,
                    db=db,
                )
                db.commit()
    finally:
        db.close()
    return total


async def run_forever(interval: float = 1.0) -> None:
    """Polling loop used by the worker process."""
    logger.info("queue worker started (interval=%ss)", interval)
    while True:
        try:
            await run_once()
        except Exception as exc:  # noqa: BLE001
            logger.exception("worker cycle error: %s", exc)
        await asyncio.sleep(interval)


def main() -> None:
    import os

    logging.basicConfig(level=logging.INFO)
    from ..db import init_db

    init_db()  # ensure tables exist even if the API hasn't booted yet
    poll = float(os.environ.get("STORYWATCHER_WORKER_POLL", "1.0"))
    asyncio.run(run_forever(interval=poll))


if __name__ == "__main__":
    main()