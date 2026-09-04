"""Combined worker process: runs both the periodic story-fetch scheduler and the
queue-view worker inside a single process.

Two things are important here:

1. Telethon session files are SQLite-backed and cannot be opened by more than
   one process at a time, so a single process must own the client.
2. Even within one process, two coroutines must not touch the Telegram client
   concurrently: Telethon writes session state synchronously around network
   awaits, and a second writer during that window raises
   "database is locked". Hence the sequential supercycle below instead of
   ``asyncio.gather``.

Watchdog: a heartbeat file is written each cycle.  If consecutive cycle errors
exceed MAX_CONSECUTIVE_ERRORS the process exits so Docker can restart it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time

from ..db import init_db, SessionLocal
from . import queue_worker, scheduler

logger = logging.getLogger("storywatcher.combined")

HEARTBEAT_PATH = os.environ.get("WORKER_HEARTBEAT", "/tmp/worker_heartbeat")
MAX_CONSECUTIVE_ERRORS = int(os.environ.get("WORKER_MAX_ERRORS", "10"))


def _write_heartbeat() -> None:
    """Atomically write the current monotonic time to the heartbeat file."""
    try:
        tmp = HEARTBEAT_PATH + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(str(time.time()))
        os.replace(tmp, HEARTBEAT_PATH)
    except OSError:
        pass


def _heartbeat_watchdog() -> None:
    """Background thread: writes a heartbeat file every 5 seconds so Docker
    healthcheck can detect a stuck main loop even during long discovery cycles."""
    while True:
        _write_heartbeat()
        time.sleep(5)


def _cleanup_old_data() -> None:
    """Remove old VIEWED queue items, stale activity logs, and excess
    analytics snapshots to prevent unbounded table growth.  Runs once per hour."""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        # Delete VIEWED queue items older than 7 days
        result = db.execute(
            text("DELETE FROM story_queue WHERE status = 'VIEWED' AND completed_at < NOW() - INTERVAL '7 days'")
        )
        if result.rowcount:
            logger.info("cleanup: removed %d old VIEWED queue items", result.rowcount)
        # Delete FAILED queue items older than 30 days (keep for debugging)
        result = db.execute(
            text("DELETE FROM story_queue WHERE status = 'FAILED' AND completed_at < NOW() - INTERVAL '30 days'")
        )
        if result.rowcount:
            logger.info("cleanup: removed %d old FAILED queue items", result.rowcount)
        # Delete activity logs older than 30 days (keep recent history)
        result = db.execute(
            text("DELETE FROM activity_logs WHERE created_at < NOW() - INTERVAL '30 days'")
        )
        if result.rowcount:
            logger.info("cleanup: removed %d old activity log entries", result.rowcount)
        # Clean up analytics snapshots: keep only the last snapshot per story per day
        # for the last 30 days.  Delete all snapshots older than 30 days, then
        # deduplicate within the 30-day window (keep only the latest per story/day).
        result = db.execute(
            text("""
                DELETE FROM story_stats_snapshots
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY story_id, DATE(collected_at)
                                   ORDER BY collected_at DESC
                               ) AS rn
                        FROM story_stats_snapshots
                        WHERE collected_at < NOW() - INTERVAL '30 days'
                    ) sub
                    WHERE rn > 1
                )
            """)
        )
        if result.rowcount:
            logger.info("cleanup: removed %d old duplicate snapshots (>30d)", result.rowcount)
        # Also delete snapshots older than 90 days entirely
        result = db.execute(
            text("DELETE FROM story_stats_snapshots WHERE collected_at < NOW() - INTERVAL '90 days'")
        )
        if result.rowcount:
            logger.info("cleanup: removed %d very old snapshots (>90d)", result.rowcount)
        # Deduplicate snapshots within the 30-day window (keep latest per story/day)
        result = db.execute(
            text("""
                DELETE FROM story_stats_snapshots
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY story_id, DATE(collected_at)
                                   ORDER BY collected_at DESC
                               ) AS rn
                        FROM story_stats_snapshots
                        WHERE collected_at >= NOW() - INTERVAL '30 days'
                    ) sub
                    WHERE rn > 1
                )
            """)
        )
        if result.rowcount:
            logger.info("cleanup: removed %d duplicate snapshots within 30d window", result.rowcount)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("cleanup failed: %s", exc)
    finally:
        db.close()


async def run() -> None:
    init_db()  # ensure tables exist even if the API hasn't booted yet
    sync_interval = float(os.environ.get("STORYWATCHER_SYNC_INTERVAL", "30"))
    poll_interval = float(os.environ.get("STORYWATCHER_WORKER_POLL", "1.0"))
    logger.info(
        "combined worker started (sync=%ss, poll=%ss)", sync_interval, poll_interval
    )
    # Start the watchdog thread so heartbeat is always fresh.
    t = threading.Thread(target=_heartbeat_watchdog, daemon=True)
    t.start()

    last_sync = 0.0
    last_cleanup = 0.0
    consecutive_errors = 0
    discovery_task: asyncio.Task | None = None

    while True:
        _write_heartbeat()  # mark liveness at the top so healthcheck doesn't false-positive
        now = time.monotonic()
        cycle_had_error = False

        # 1) Drain the view queue FIRST — this is time-sensitive (stories expire).
        try:
            t0 = time.monotonic()
            processed = await queue_worker.run_once()
            elapsed = time.monotonic() - t0
            if elapsed > 2 or processed:
                logger.info("queue_worker: processed=%s elapsed=%.1fs", processed, elapsed)
        except Exception as exc:  # noqa: BLE001
            logger.exception("worker cycle error: %s", exc)
            cycle_had_error = True

        # 2) Periodic cleanup of old VIEWED queue items and activity logs.
        if now - last_cleanup >= 3600:  # every hour
            try:
                _cleanup_old_data()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cleanup error: %s", exc)
            last_cleanup = now

        # 3) Periodic story sync (respects its own interval).
        if now - last_sync >= sync_interval:
            try:
                await scheduler.run_once()
                await scheduler.run_analytics_once()
            except Exception as exc:  # noqa: BLE001
                logger.exception("scheduler cycle error: %s", exc)
                cycle_had_error = True
            last_sync = now

        # 4) Global story discovery — run as a background task so it doesn't
        #    block queue processing (discovery can take minutes due to
        #    FloodWait from Telegram's SearchPosts rate limit).
        if discovery_task is None or discovery_task.done():
            async def _run_discovery():
                try:
                    t0 = time.monotonic()
                    await scheduler.run_discovery_once()
                    elapsed = time.monotonic() - t0
                    logger.info("discovery cycle completed in %.1fs", elapsed)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("discovery cycle error: %s", exc)
            discovery_task = asyncio.create_task(_run_discovery())

        # --- Watchdog bookkeeping ---
        if cycle_had_error:
            consecutive_errors += 1
            logger.warning(
                "consecutive error streak: %d / %d",
                consecutive_errors,
                MAX_CONSECUTIVE_ERRORS,
            )
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.critical(
                    "too many consecutive errors (%d) — exiting to trigger restart",
                    consecutive_errors,
                )
                sys.exit(1)
        else:
            consecutive_errors = 0

        _write_heartbeat()  # also update after cycle completes
        await asyncio.sleep(poll_interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()