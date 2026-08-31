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

CONNECT_TIMEOUT = 30  # seconds to wait for Telegram connect

from ..db import SessionLocal
from ..models import AccountStatus, TelegramAccount
from ..services.settings_service import SettingsService
from ..stories import discovery
from ..stories.monitor import StoryMonitor, load_contacts_into
from ..telegram import client_manager as cm
from ..analytics.service import collect_account

logger = logging.getLogger("storywatcher.scheduler")


async def sync_account(account: TelegramAccount) -> int:
    for _attempt in range(3):
        db = SessionLocal()
        try:
            acc = db.get(TelegramAccount, account.id)
            if acc is None or not acc.session_path:
                return 0
            if acc.status == AccountStatus.DISCONNECTED.value:
                return 0
            client = await asyncio.wait_for(cm.connect(acc), timeout=CONNECT_TIMEOUT)
            if not client.is_connected():
                acc.status = AccountStatus.DISCONNECTED.value
                db.commit()
                return 0
            if not await asyncio.wait_for(client.is_user_authorized(), timeout=CONNECT_TIMEOUT):
                acc.status = AccountStatus.DISCONNECTED.value
                acc.monitoring = False
                # Do NOT clear session_path — the file may still be
                # valid but need re-auth. Clearing it destroys the
                # auth data and makes the account disappear.
                db.commit()
                return 0
            monitor = StoryMonitor(client, acc, db)
            lookup = monitor._load_sets()
            await load_contacts_into(client, acc, lookup)
            monitor._lookup = lookup
            count = await monitor.fetch_available(resync=True)
            acc.status = AccountStatus.ACTIVE.value
            acc.last_seen_at = datetime.now(timezone.utc)
            db.commit()
            return count
        except Exception as exc:
            is_locked = "database is locked" in str(exc).lower()
            if is_locked and _attempt < 2:
                logger.warning("sync_account(%s) database locked, retry %d", account.id, _attempt + 1)
                db.rollback()
                db.close()
                await asyncio.sleep(2 ** _attempt)
                continue
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
            except Exception:
                db.rollback()
            return 0
        finally:
            db.close()


async def run_analytics_once() -> None:
    db = SessionLocal()
    try:
        accounts = db.query(TelegramAccount).filter(TelegramAccount.status == AccountStatus.ACTIVE.value).all()
    finally:
        db.close()
    for account in accounts:
        local = SessionLocal()
        try:
            acc = local.get(TelegramAccount, account.id)
            if acc is not None and acc.session_path and acc.status not in (AccountStatus.DISCONNECTED.value, AccountStatus.AUTH_REQUIRED.value):
                client = await asyncio.wait_for(cm.connect(acc), timeout=CONNECT_TIMEOUT)
                if client.is_connected() and await asyncio.wait_for(client.is_user_authorized(), timeout=CONNECT_TIMEOUT):
                    await collect_account(acc.id, local, client)
        except Exception as exc:  # noqa: BLE001
            logger.warning("analytics sync account=%s failed: %s", account.id, exc)
        finally:
            local.close()


async def run_once() -> None:
    db = SessionLocal()
    accounts = []
    try:
        accounts = (
            db.query(TelegramAccount)
            .filter(TelegramAccount.monitoring.is_(True), TelegramAccount.session_path.isnot(None), TelegramAccount.status != AccountStatus.DISCONNECTED.value)
            .all()
        )
    finally:
        db.close()
    for account in accounts:
        await sync_account(account)


# Per-user discovery timing: {user_id: last_run_monotonic}
_last_discovery_ts: dict[int, float] = {}

# Round-robin pointer per user so auto-added geo places are searched in
# rotation across discovery cycles (bounded by the configured search budget)
# instead of firing one stories.searchPosts call per place every cycle.
_auto_venue_offset: dict[int, int] = {}

# Round-robin pointer for hashtags: search a subset each cycle.
_hashtag_offset: dict[int, int] = {}


async def run_discovery_once() -> None:
    """Run per-user story discovery (hashtags / geo) when due or when forced.

    Each web-app user has their own discovery settings (hashtags, locations,
    interval).  We iterate over all active accounts grouped by user_id and
    run discovery with the settings belonging to that user.
    """
    db = SessionLocal()
    try:
        accounts = (
            db.query(TelegramAccount)
            .filter(TelegramAccount.monitoring.is_(True), TelegramAccount.session_path.isnot(None), TelegramAccount.status != AccountStatus.DISCONNECTED.value)
            .all()
        )
    finally:
        db.close()

    # Group accounts by user_id and pick one representative per user.
    user_accounts: dict[int, list[TelegramAccount]] = {}
    for acc in accounts:
        uid = acc.user_id
        if uid is None:
            continue
        user_accounts.setdefault(uid, []).append(acc)

    now = time.monotonic()

    # Collect (account, cfg) pairs for users that are due for discovery.
    # We build a flat list first so that accounts from different users are
    # interleaved — otherwise one user with many hashtags/venues starves
    # the others.
    pending: list[tuple[TelegramAccount, dict]] = []
    for uid, accs in user_accounts.items():
        db2 = SessionLocal()
        try:
            svc = SettingsService(db2, uid)
            cfg = svc.get("discovery")
            if not cfg.get("enabled"):
                continue
            interval = max(int(cfg.get("search_interval", 300)), 60)
            force = bool(cfg.pop("force_next", False))
            if force:
                svc.set("discovery", cfg)  # clear the flag
            last = _last_discovery_ts.get(uid, 0.0)
            if not force and (now - last < interval):
                continue
            _last_discovery_ts[uid] = now
        finally:
            db2.close()
        for acc in accs:
            pending.append((acc, cfg))

    # Round-robin: pick one account per user per iteration so that a single
    # large user (500+ hashtags) does not block smaller users.
    # Build per-user buckets.
    user_buckets: dict[int, list[tuple[TelegramAccount, dict]]] = {}
    for acc, cfg in pending:
        user_buckets.setdefault(acc.user_id or 0, []).append((acc, cfg))
    while user_buckets:
        exhausted = []
        for uid_bucket, items in user_buckets.items():
            if not items:
                exhausted.append(uid_bucket)
                continue
            acc, cfg = items.pop(0)
            await _discover_account(acc, cfg)
        for uid_bucket in exhausted:
            del user_buckets[uid_bucket]


async def _discover_account(account: TelegramAccount, cfg: dict) -> None:
    db = SessionLocal()
    try:
        acc = db.get(TelegramAccount, account.id)
        if acc is None or not acc.session_path or acc.status == AccountStatus.DISCONNECTED.value:
            return
        client = await asyncio.wait_for(cm.connect(acc), timeout=CONNECT_TIMEOUT)
        if not client.is_connected() or not await asyncio.wait_for(client.is_user_authorized(), timeout=CONNECT_TIMEOUT):
            return
        monitor = StoryMonitor(client, acc, db)
        lookup = monitor._load_sets()
        await load_contacts_into(client, acc, lookup)
        monitor._lookup = lookup

        limit = int(cfg.get("search_results_max", 50))
        all_hashtags = cfg.get("hashtags") or [] if cfg.get("hashtags_enabled", True) else []
        all_locations = list(cfg.get("locations") or [])
        # Rotate through hashtags: search at most `hashtag_budget` per cycle
        # to avoid flooding Telegram with too many SearchPosts requests.
        hashtag_budget = max(5, min(30, len(all_hashtags) // 10 + 5))
        uid = account.user_id or 0
        if all_hashtags:
            h_offset = _hashtag_offset.get(uid, 0) % len(all_hashtags)
            hashtags = (all_hashtags[h_offset:] + all_hashtags[:h_offset])[:hashtag_budget]
            _hashtag_offset[uid] = (h_offset + hashtag_budget) % len(all_hashtags)
        else:
            hashtags = []
        # Same for locations: rotate through them with a budget to prevent
        # one user with thousands of venues from starving others.
        location_budget = max(5, min(30, len(all_locations) // 10 + 5))
        auto_locations: list[str] = []
        # When auto-add is enabled, rotate through ALL collected geo places,
        # searching at most ``searches_per_hour`` of them per cycle.
        if cfg.get("auto_add_places", True):
            from ..models import GeoPlace

            auto_budget = max(1, int(cfg.get("searches_per_hour", 10)))
            places = db.query(GeoPlace).order_by(GeoPlace.id).all()
            existing_vids = {
                l[len("venue:"):] for l in all_locations if l.startswith("venue:")
            }
            auto = [
                f"venue:{p.venue_id}"
                for p in places
                if p.venue_id and p.venue_id not in existing_vids
            ]
            if auto:
                start = _auto_venue_offset.get(uid, 0) % len(auto)
                auto_locations = (auto[start:] + auto[:start])[:auto_budget]
                _auto_venue_offset[uid] = (start + auto_budget) % len(auto)
        # Rotate through manually-configured locations.
        if all_locations:
            l_offset = _hashtag_offset.get(uid * 1000 + 1, 0) % len(all_locations)
            manual_locations = (all_locations[l_offset:] + all_locations[:l_offset])[:location_budget]
            _hashtag_offset[uid * 1000 + 1] = (l_offset + location_budget) % len(all_locations)
        else:
            manual_locations = []
        locations = manual_locations + auto_locations
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