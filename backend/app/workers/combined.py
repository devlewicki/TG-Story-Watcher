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
from ..telegram import client_manager as cm
from ..vpn_monitor import VpnMonitor

logger = logging.getLogger("storywatcher.combined")

HEARTBEAT_PATH = os.environ.get("WORKER_HEARTBEAT", "/tmp/worker_heartbeat")
MAX_CONSECUTIVE_ERRORS = int(os.environ.get("WORKER_MAX_ERRORS", "10"))
# Seconds the main loop may go without completing a cycle before the watchdog
# kills the process so Docker restarts it. The queue sweep itself is fast;
# long discovery runs happen as a background task, so a stall is a real hang.
STALL_TIMEOUT = float(os.environ.get("WORKER_STALL_TIMEOUT", "240"))
LOG_STALL_EVERY = 60.0

# A discovery cycle is supposed to finish (flood-waits included). If it runs
# longer than this we assume an unresolvable hang (e.g. half-open TCP through a
# dropped proxy tunnel) and hard-cancel it so a fresh cycle can start.
DISCOVERY_WRAP_TIMEOUT = float(os.environ.get("WORKER_DISCOVERY_TIMEOUT", "1200"))

# Monotonic timestamp of the last completed main-loop cycle. Written by run(),
# read by the watchdog thread. Zero means "loop hasn't ticked yet".
_last_cycle_ts = 0.0


def _write_heartbeat() -> None:
    """Atomically write the current monotonic time to the heartbeat file."""
    try:
        tmp = HEARTBEAT_PATH + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(str(time.time()))
        os.replace(tmp, HEARTBEAT_PATH)
    except OSError:
        pass


def _mark_cycle() -> None:
    global _last_cycle_ts
    _last_cycle_ts = time.monotonic()


def _heartbeat_watchdog() -> None:
    """Background thread: writes a heartbeat file every 5 seconds AND exits the
    process if the main loop has not marked a completed cycle within
    STALL_TIMEOUT.

    The old implementation wrote the heartbeat unconditionally from this thread,
    so Docker reported ``healthy`` even while the main loop was wedged (K-01).
    """
    last_logged = 0.0
    while True:
        now = time.monotonic()
        # If the main loop hasn't ever ticked (startup), wait for it.
        if _last_cycle_ts and (now - _last_cycle_ts) > STALL_TIMEOUT:
            if now - last_logged >= LOG_STALL_EVERY:
                logger.critical(
                    "main loop stalled: no cycle completed for %.0fs — exiting to trigger restart",
                    now - _last_cycle_ts,
                )
                last_logged = now
            # Give the loop one more grace period to recover, then hard-exit.
            if (now - _last_cycle_ts) > STALL_TIMEOUT * 2:
                os._exit(1)
        _write_heartbeat()
        time.sleep(5)


def _cleanup_old_data() -> None:
    """Remove old VIEWED queue items, stale activity logs, and excess
    analytics snapshots to prevent unbounded table growth.  Runs once per hour.

    Supports both PostgreSQL and SQLite (used in local development)."""
    db = SessionLocal()
    is_postgres = str(db.bind.url).startswith("postgresql")
    try:
        from sqlalchemy import text
        from datetime import datetime, timedelta, timezone
        now_utc = datetime.now(timezone.utc)
        if is_postgres:
            # --- PostgreSQL: use native INTERVAL syntax ---
            result = db.execute(text("DELETE FROM story_queue WHERE status = 'VIEWED' AND completed_at < NOW() - INTERVAL '7 days'"))
            if result.rowcount:
                logger.info("cleanup: removed %d old VIEWED queue items", result.rowcount)
            result = db.execute(text("DELETE FROM story_queue WHERE status = 'FAILED' AND completed_at < NOW() - INTERVAL '30 days'"))
            if result.rowcount:
                logger.info("cleanup: removed %d old FAILED queue items", result.rowcount)
            result = db.execute(text("DELETE FROM activity_logs WHERE created_at < NOW() - INTERVAL '30 days'"))
            if result.rowcount:
                logger.info("cleanup: removed %d old activity log entries", result.rowcount)
            result = db.execute(text("DELETE FROM story_stats_snapshots WHERE collected_at < NOW() - INTERVAL '90 days'"))
            if result.rowcount:
                logger.info("cleanup: removed %d very old snapshots (>90d)", result.rowcount)
            # Deduplicate within 30-day window
            result = db.execute(text("""
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
            """))
            if result.rowcount:
                logger.info("cleanup: removed %d duplicate snapshots within 30d window", result.rowcount)
        else:
            # --- SQLite: use parameterized datetime thresholds ---
            cutoff_7d = (now_utc - timedelta(days=7)).isoformat()
            cutoff_30d = (now_utc - timedelta(days=30)).isoformat()
            cutoff_90d = (now_utc - timedelta(days=90)).isoformat()
            result = db.execute(text("DELETE FROM story_queue WHERE status = 'VIEWED' AND completed_at < :cutoff"), {"cutoff": cutoff_7d})
            if result.rowcount:
                logger.info("cleanup: removed %d old VIEWED queue items", result.rowcount)
            result = db.execute(text("DELETE FROM story_queue WHERE status = 'FAILED' AND completed_at < :cutoff"), {"cutoff": cutoff_30d})
            if result.rowcount:
                logger.info("cleanup: removed %d old FAILED queue items", result.rowcount)
            result = db.execute(text("DELETE FROM activity_logs WHERE created_at < :cutoff"), {"cutoff": cutoff_30d})
            if result.rowcount:
                logger.info("cleanup: removed %d old activity log entries", result.rowcount)
            result = db.execute(text("DELETE FROM story_stats_snapshots WHERE collected_at < :cutoff"), {"cutoff": cutoff_90d})
            if result.rowcount:
                logger.info("cleanup: removed %d very old snapshots (>90d)", result.rowcount)
            # SQLite doesn't support window functions in DELETE subqueries the same
            # way, so dedup is skipped for SQLite — it handles dedup less
            # gracefully but won't grow unbounded with 90d cutoff above.
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
    analytics_interval = float(os.environ.get("STORYWATCHER_ANALYTICS_INTERVAL", "3600"))
    logger.info(
        "combined worker started (sync=%ss, poll=%ss, analytics=%ss)",
        sync_interval, poll_interval, analytics_interval,
    )
    # Start the watchdog thread so heartbeat is always fresh.
    _mark_cycle()
    t = threading.Thread(target=_heartbeat_watchdog, daemon=True)
    t.start()

    last_sync = 0.0
    last_analytics = 0.0
    last_cleanup = 0.0
    consecutive_errors = 0
    discovery_task: asyncio.Task | None = None
    discovery_started: float | None = None

    # VPN IP monitor: detect IP changes and proactively disconnect clients.
    from ..config import get_settings
    _settings = get_settings()
    vpn_monitor: VpnMonitor | None = None
    if _settings.telegram_proxy_enabled and _settings.telegram_proxy_host:
        vpn_monitor = VpnMonitor(
            proxy_host=_settings.telegram_proxy_host,
            proxy_port=_settings.telegram_proxy_port or 1080,
            check_interval=float(os.environ.get("VPN_IP_CHECK_INTERVAL", "30")),
        )
        logger.info("VPN IP monitor enabled (host=%s, interval=%ss)",
                     _settings.telegram_proxy_host, vpn_monitor._check_interval)

    async def _on_vpn_ip_change() -> None:
        """Callback: disconnect all Telegram clients when VPN IP changes."""
        logger.warning("VPN IP change detected — disconnecting all Telegram clients")
        try:
            await cm.shutdown_all()
        except Exception:
            logger.debug("shutdown_all during VPN IP change failed", exc_info=True)

    while True:
        _write_heartbeat()  # mark liveness at the top so healthcheck doesn't false-positive
        now = time.monotonic()
        cycle_had_error = False

        # 0) VPN IP healthcheck — proactively disconnect on IP change.
        if vpn_monitor is not None:
            try:
                await vpn_monitor.tick(_on_vpn_ip_change)
            except Exception as exc:  # noqa: BLE001
                logger.debug("vpn_monitor tick failed: %s", exc)

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
        _mark_cycle()  # queue drain completed → main loop is alive

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
            except Exception as exc:  # noqa: BLE001
                logger.exception("scheduler cycle error: %s", exc)
                cycle_had_error = True
            last_sync = now
        else:
            _mark_cycle()

        # 4) Analytics on its own (much larger) interval. Full-archive collection
        #    used to run every sync cycle — a flood/freeze risk on large archives.
        if now - last_analytics >= analytics_interval:
            _mark_cycle()  # analytics collection may legitimately run for minutes
            try:
                await scheduler.run_analytics_once()
            except Exception as exc:  # noqa: BLE001
                logger.exception("analytics cycle error: %s", exc)
            last_analytics = now
        else:
            _mark_cycle()

        # 5) Global story discovery — run as a background task so it doesn't
        #    block queue processing (discovery can take minutes due to
        #    FloodWait from Telegram's SearchPosts rate limit).
        if discovery_task is not None and not discovery_task.done():
            # Stale-task protection: a discovery that outlives
            # DISCOVERY_WRAP_TIMEOUT is almost certainly hung on dead telethon
            # awaits. Without cancelling it, the ``done()`` guard below would
            # starve every future discovery cycle until process restart (the
            # outage where the project silently stopped at 14:14 UTC).
            if discovery_started is not None and (now - discovery_started) > DISCOVERY_WRAP_TIMEOUT:
                logger.critical(
                    "discovery cycle overran %.0fs — cancelling stale task",
                    now - discovery_started,
                )
                discovery_task.cancel()
                try:
                    await discovery_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                discovery_task = None
                discovery_started = None
        if discovery_task is None or discovery_task.done():
            async def _run_discovery():
                try:
                    t0 = time.monotonic()
                    await scheduler.run_discovery_once()
                    elapsed = time.monotonic() - t0
                    logger.info("discovery cycle completed in %.1fs", elapsed)
                except asyncio.CancelledError:
                    logger.warning("discovery cycle cancelled after %.1fs", time.monotonic() - t0)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("discovery cycle error: %s", exc)
            discovery_task = asyncio.create_task(_run_discovery())
            discovery_started = now

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
        _mark_cycle()
        await asyncio.sleep(poll_interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("worker interrupted, disconnecting Telegram clients")
        try:
            asyncio.run(cm.shutdown_all())
        except Exception:
            logger.exception("error disconnecting Telegram clients during worker shutdown")


if __name__ == "__main__":
    main()