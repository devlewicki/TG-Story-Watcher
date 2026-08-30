"""
Scheduler worker: periodically fetches available stories for monitoring-enabled
accounts (the "burst" sync via ``stories.getAllStories``) and runs global story
Discovery (hashtag/geo search via ``stories.searchPosts``) on its own interval.
The real-time update stream would be fed by an ``events`` handler registered on
each connected client; for the MVP the periodic sync is the primary ingestion
path.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from ..db import SessionLocal
from ..models import AccountStatus, TelegramAccount
from ..services.settings_service import SettingsService
from ..stories import discovery
from ..stories.monitor import StoryMonitor, load_contacts_into
from ..telegram import client_manager as cm

logger = logging.getLogger("storywatcher.scheduler")


async def sync_account(account: TelegramAccount) -> int:
    db = SessionLocal()
    try:
        # Re-load the account in this session: the caller may pass an object
        # detached from a different (already closed) session.
        acc = db.get(TelegramAccount, account.id)
        if acc is None:
            return 0

        client = await cm.connect(acc)
        if not client.is_connected():
            acc.status = AccountStatus.DISCONNECTED.value
            db.commit()
            return 0
        if not await client.is_user_authorized():
            acc.status = AccountStatus.AUTH_REQUIRED.value
            db.commit()
            return 0

        monitor = StoryMonitor(client, acc, db)
        # Load the contact set so the "is contact" filter has real data, then
        # make the monitor reuse this lookup for the burst sync below.
        lookup = monitor._load_sets()
        await load_contacts_into(client, acc, lookup)
        monitor._lookup = lookup

        count = await monitor.fetch_available(resync=True)
        acc.status = AccountStatus.ACTIVE.value
        acc.last_seen_at = datetime.now(timezone.utc)
        db.commit()
        return count
    except Exception as exc:  # noqa: BLE001
        logger.error("sync_account(%s) failed: %s", account.id, exc)
        try:
            acc = db.get(TelegramAccount, account.id)
            if acc is not None:
                acc.status = AccountStatus.ERROR.value
            from ..services import activity

            activity.log(
                f"scheduler sync failed: {exc}",
                event_type="worker_error",
                level="ERROR",
                account_id=account.id,
                db=db,
            )
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return 0
    finally:
        db.close()


async def run_once() -> None:
    db = SessionLocal()
    accounts = []
    try:
        accounts = (
            db.query(TelegramAccount)
            .filter(TelegramAccount.monitoring.is_(True))
            .all()
        )
    finally:
        db.close()
    for account in accounts:
        await sync_account(account)


_last_discovery_ts = 0.0

# Round-robin pointer so auto-added geo places are searched in rotation across
# discovery cycles (bounded by the configured search budget) instead of firing
# one stories.searchPosts call per place every cycle.
_auto_venue_offset: int = 0


async def run_discovery_once() -> None:
    """Run global story discovery (hashtags / geo) when due or when forced.

    The interval comes from the discovery settings; the API can set
    ``force_next`` to trigger an immediate run on the next cycle.
    """
    global _last_discovery_ts
    now = time.monotonic()

    db = SessionLocal()
    try:
        svc = SettingsService(db)
        cfg = svc.get("discovery")
        if not cfg.get("enabled"):
            return
        # Global story search (searchPosts) is heavily rate-limited by
        # Telegram; searching more often than ~1/min with several hashtags and
        # locations reliably triggers FloodWait, so clamp the minimum.
        interval = max(int(cfg.get("search_interval", 300)), 60)
        force = bool(cfg.pop("force_next", False))
        if force:
            svc.set("discovery", cfg)  # clear the flag
        accounts = (
            db.query(TelegramAccount)
            .filter(TelegramAccount.monitoring.is_(True))
            .all()
        )
    finally:
        db.close()

    if not force and (now - _last_discovery_ts < interval):
        return
    _last_discovery_ts = now

    for account in accounts:
        await _discover_account(account, cfg)


async def _discover_account(account: TelegramAccount, cfg: dict) -> None:
    db = SessionLocal()
    try:
        acc = db.get(TelegramAccount, account.id)
        if acc is None:
            return
        client = await cm.connect(acc)
        if not client.is_connected() or not await client.is_user_authorized():
            return
        monitor = StoryMonitor(client, acc, db)
        lookup = monitor._load_sets()
        await load_contacts_into(client, acc, lookup)
        monitor._lookup = lookup

        limit = int(cfg.get("search_results_max", 50))
        hashtags = cfg.get("hashtags") or []
        locations = list(cfg.get("locations") or [])
        # When auto-add is enabled, rotate through ALL collected geo places,
        # searching at most ``searches_per_hour`` of them per cycle. Searching
        # every place every cycle would fire thousands of stories.searchPosts
        # calls per run (FloodWait + activity-log spam).
        if cfg.get("auto_add_places", True):
            global _auto_venue_offset
            from ..models import GeoPlace

            budget = max(1, int(cfg.get("searches_per_hour", 10)))
            places = db.query(GeoPlace).order_by(GeoPlace.id).all()
            existing_vids = {
                l[len("venue:"):] for l in locations if l.startswith("venue:")
            }
            auto = [
                f"venue:{p.venue_id}"
                for p in places
                if p.venue_id and p.venue_id not in existing_vids
            ]
            if auto:
                start = _auto_venue_offset % len(auto)
                locations.extend((auto[start:] + auto[:start])[:budget])
                _auto_venue_offset = (start + budget) % len(auto)
        # Geolocation first: it is the primary discovery mode and may be slow,
        # so big hashtag lists must not starve it.
        if locations:
            await discovery.search_locations(monitor, locations, limit)
        if hashtags:
            await discovery.search_hashtags(monitor, hashtags, limit)
    except Exception as exc:  # noqa: BLE001
        logger.error("discover_account(%s) failed: %s", account.id, exc)
    finally:
        db.close()


async def run_forever(interval: float) -> None:
    logger.info("scheduler started (interval=%ss)", interval)
    while True:
        try:
            await run_once()
        except Exception as exc:  # noqa: BLE001
            logger.exception("scheduler cycle error: %s", exc)
        await asyncio.sleep(interval)


def main() -> None:
    import os

    logging.basicConfig(level=logging.INFO)
    from ..db import init_db

    init_db()  # ensure tables exist even if the API hasn't booted yet
    interval = float(os.environ.get("STORYWATCHER_SYNC_INTERVAL", "30"))
    asyncio.run(run_forever(interval=interval))


if __name__ == "__main__":
    main()