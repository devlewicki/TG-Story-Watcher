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
import os
import time
from datetime import datetime, timezone

from telethon.errors import AuthKeyDuplicatedError, AuthKeyUnregisteredError, UnauthorizedError

CONNECT_TIMEOUT = 30  # seconds to wait for Telegram connect

# Hard ceiling for one account's discovery work. Covers connect, contact sync,
# identity refresh and every search in this cycle; anything longer is a hang
# (half-open TCP through a dropped tunnel) and gets aborted.
DISCOVERY_ACCOUNT_TIMEOUT = 300

from ..db import SessionLocal
from ..models import AccountStatus, TelegramAccount
from ..services.settings_service import SettingsService
from ..api.timezone import user_today
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
            await _maybe_update_identity(acc, client)
            monitor = StoryMonitor(client, acc, db)
            lookup = monitor._load_sets()
            await load_contacts_into(client, acc, lookup)
            monitor._lookup = lookup
            count = await monitor.fetch_available()
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
            # AuthKey duplicated: VPN IP changed — session is permanently
            # invalidated.  Delete the session file and mark AUTH_REQUIRED so
            # the user can re-login from the web UI.
            is_auth_dup = isinstance(exc, AuthKeyDuplicatedError) or "authorization key" in str(exc).lower()
            if is_auth_dup:
                logger.error("sync_account(%s) AuthKeyDuplicatedError — session invalidated by IP change, marking AUTH_REQUIRED", account.id)
                db.rollback()
                db.close()
                try:
                    await cm.mark_account_auth_required(account.id, drop_session=True)
                except Exception:
                    pass
                return 0
            # Auth key unregistered: Telegram revoked the session (logout /
            # forced termination) — the account needs a fresh login, but the
            # session file is kept so the re-login flow can reuse it.
            is_auth_unreg = isinstance(exc, (AuthKeyUnregisteredError, UnauthorizedError)) or "key is not registered" in str(exc).lower()
            if is_auth_unreg:
                logger.error("sync_account(%s) session unregistered — marking AUTH_REQUIRED", account.id)
                db.rollback()
                db.close()
                try:
                    await cm.mark_account_auth_required(account.id, drop_session=False)
                except Exception:
                    pass
                return 0
            # Connection errors: force a full reconnect before retrying.
            is_conn = isinstance(exc, (ConnectionError, TimeoutError)) or "disconnected" in str(exc).lower()
            if is_conn and _attempt < 2:
                logger.warning("sync_account(%s) connection error, reconnecting (attempt %d): %s", account.id, _attempt + 1, exc)
                db.rollback()
                db.close()
                try:
                    await cm.reconnect(acc)
                except Exception:
                    logger.debug("reconnect for account %s failed", account.id, exc_info=True)
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
                    await _maybe_update_identity(acc, client)
                    local.commit()
                    await collect_account(acc.id, local, client)
        except AuthKeyDuplicatedError as exc:
            logger.warning("analytics sync account=%s AuthKeyDuplicatedError — marking AUTH_REQUIRED", account.id)
            local.close()
            try:
                await cm.mark_account_auth_required(account.id, drop_session=True)
            except Exception:
                pass
            continue
        except (AuthKeyUnregisteredError, UnauthorizedError) as exc:
            logger.warning("analytics sync account=%s session unregistered — marking AUTH_REQUIRED", account.id)
            local.close()
            try:
                await cm.mark_account_auth_required(account.id, drop_session=False)
            except Exception:
                pass
            continue
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

# Cache for update_account_identity: {account_id: last_update_monotonic}
# Avoids calling get_me() on Telegram every sync/discovery/analytics cycle.
_identity_last_update: dict[int, float] = {}
IDENTITY_CACHE_TTL = 600  # 10 minutes


async def _maybe_update_identity(acc: TelegramAccount, client) -> None:
    """Call update_account_identity at most once per IDENTITY_CACHE_TTL."""
    now = time.monotonic()
    last = _identity_last_update.get(acc.id, 0.0)
    if now - last < IDENTITY_CACHE_TTL:
        return
    await cm.update_account_identity(acc, client)
    _identity_last_update[acc.id] = now

# Round-robin pointer per user so auto-added geo places are searched in
# rotation across discovery cycles (bounded by the configured search budget)
# instead of firing one stories.searchPosts call per place every cycle.
_auto_venue_offset: dict[int, int] = {}

# Round-robin pointer for hashtags: search a subset each cycle.
_hashtag_offset: dict[int, int] = {}

# Round-robin pointer for manual locations: search a subset each cycle.
_location_offset: dict[int, int] = {}

# Round-robin pointer for geo-search venues: search a subset each cycle.
_geo_venue_offset: dict[int, int] = {}

# Cache of venues within a saved geo radius. The bbox+haversine scan is run
# for every geo-enabled user on every discovery cycle; the result only changes
# when the config or the collected places change, so memoise it briefly.
_geo_radius_cache: dict[int, tuple[tuple[float, float, float], float, list[str]]] = {}
GEO_RADIUS_CACHE_TTL = 600.0


def _dedupe_locations(locations: list[str]) -> list[str]:
    """Drop venues that appear more than once across manual/auto/geo lists.

    Keeps the first occurrence (order preserved) and keys by venue id, so a
    ``venue:4c45...`` coming from all three sources is searched exactly once.
    Non-venue entries (``city:...``, bare titles, raw coords) are kept as-is.
    """
    seen_vids: set[str] = set()
    deduped: list[str] = []
    for loc in locations:
        key = loc[len("venue:"):] if loc.startswith("venue:") else loc
        if key in seen_vids:
            continue
        seen_vids.add(key)
        deduped.append(loc)
    return deduped


def _compute_adaptive_search_params(db, user_id: int) -> dict:
    """Compute adaptive search interval and result count based on queue state.

    Returns dict with keys: interval, search_results_max, should_search.
    """
    from datetime import datetime, timezone
    from ..models import StoryQueue, StoryView
    from sqlalchemy import func

    svc = SettingsService(db, user_id)
    limits = svc.get("limits")
    daily_limit = int(limits.get("views_per_day", 800))

    # Get account IDs for this user
    acc_ids = [
        a.id for a in db.query(TelegramAccount.id)
        .filter(TelegramAccount.user_id == user_id, TelegramAccount.monitoring.is_(True))
        .all()
    ]
    if not acc_ids:
        return {"interval": 300, "search_results_max": 50, "should_search": False}

    # Queue size: pending + waiting items
    queue_size = (
        db.query(func.count(StoryQueue.id))
        .filter(StoryQueue.account_id.in_(acc_ids), StoryQueue.status.in_(["PENDING", "WAITING_DELAY"]))
        .scalar() or 0
    )

    # Views completed today
    today_start = user_today(db, user_id)
    views_today = (
        db.query(func.count(StoryView.id))
        .filter(StoryView.account_id.in_(acc_ids), StoryView.viewed_at >= today_start)
        .scalar() or 0
    )

    views_remaining = max(0, daily_limit - views_today)

    # Target queue size: ~2 hours of buffer at the required rate
    # hourly_rate = daily_limit / 24
    # target = hourly_rate * 2 (2-hour buffer)
    hourly_rate = daily_limit / 24.0
    target_queue = max(10, int(hourly_rate * 2))

    # Don't search if almost nothing remaining
    if views_remaining < 10:
        return {"interval": 600, "search_results_max": 0, "should_search": False}

    # Don't search if queue is way oversized
    if queue_size >= target_queue * 2:
        return {"interval": 600, "search_results_max": 0, "should_search": False}

    # Compute needed tasks
    needed = max(0, target_queue - queue_size)

    # Adaptive interval based on queue fullness
    ratio = queue_size / max(target_queue, 1)
    if ratio < 0.2:
        interval = 60       # Queue almost empty → search every minute
    elif ratio < 0.5:
        interval = 120      # Queue low → every 2 minutes
    elif ratio < 0.8:
        interval = 300      # Queue moderate → every 5 minutes
    else:
        interval = 600      # Queue nearly full → every 10 minutes

    # Cap results: don't fetch more than needed + small buffer
    search_results_max = min(200, max(10, needed + 10))

    return {
        "interval": interval,
        "search_results_max": search_results_max,
        "should_search": True,
        "queue_size": queue_size,
        "views_today": views_today,
        "views_remaining": views_remaining,
        "target_queue": target_queue,
    }


async def run_discovery_once() -> None:
    """Run per-user story discovery with adaptive scheduling.

    Each web-app user has their own discovery settings (hashtags, locations).
    The search interval and result count are computed dynamically based on
    queue state and daily views progress.
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
    # One shared read-only session is used across all users; the only write
    # in this loop (clearing ``force_next``) commits itself, so sharing is safe.
    pending: list[tuple[TelegramAccount, dict]] = []
    read_db = SessionLocal()
    try:
        for uid, accs in user_accounts.items():
            try:
                svc = SettingsService(read_db, uid)
                cfg = svc.get("discovery")
                if not cfg.get("enabled"):
                    continue

                # Compute adaptive search parameters
                adaptive = _compute_adaptive_search_params(read_db, uid)
                if not adaptive["should_search"]:
                    logger.debug("discovery: user %d — search not needed (queue=%d, remaining=%d)",
                                 uid, adaptive.get("queue_size", 0), adaptive.get("views_remaining", 0))
                    continue

                interval = adaptive["interval"]
                force = bool(cfg.get("force_next", False))
                if force:
                    # Clear the flag without mutating ``cfg`` (it's reused below
                    # and every consumer sees the same dict object).
                    svc.set("discovery", {k: v for k, v in cfg.items() if k != "force_next"})
                last = _last_discovery_ts.get(uid, 0.0)
                if not force and (now - last < interval):
                    continue
                _last_discovery_ts[uid] = now

                # Inject adaptive search_results_max into cfg for _discover_account
                cfg["search_results_max"] = adaptive["search_results_max"]
                logger.info(
                    "discovery: user %d — searching (interval=%ds, results=%d, queue=%d/%d, views=%d/%d)",
                    uid, interval, adaptive["search_results_max"],
                    adaptive.get("queue_size", 0), adaptive.get("target_queue", 0),
                    adaptive.get("views_today", 0), adaptive.get("views_remaining", 0) + adaptive.get("views_today", 0),
                )
            except Exception:
                logger.exception("discovery: user %d — scheduling failed", uid)
                read_db.rollback()
                continue
            for acc in accs:
                pending.append((acc, cfg))
    finally:
        read_db.close()

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
            try:
                await asyncio.wait_for(
                    _discover_account(acc, cfg), timeout=DISCOVERY_ACCOUNT_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error(
                    "discover_account(%s) timed out after %ss — aborting this account's cycle",
                    acc.id, DISCOVERY_ACCOUNT_TIMEOUT,
                )
        for uid_bucket in exhausted:
            del user_buckets[uid_bucket]


async def _discover_account(account: TelegramAccount, cfg: dict) -> None:
    db = SessionLocal()
    try:
        acc = db.get(TelegramAccount, account.id)
        if acc is None or not acc.session_path or acc.status == AccountStatus.DISCONNECTED.value:
            return
        try:
            client = await asyncio.wait_for(cm.connect(acc), timeout=CONNECT_TIMEOUT)
        except (AuthKeyDuplicatedError, AuthKeyUnregisteredError, UnauthorizedError):
            logger.error("discover_account(%s) auth failure on connect", account.id)
            # Fall through to outer auth handlers.
            raise
        except (ConnectionError, OSError, TimeoutError) as exc:
            logger.warning("discover_account(%s) connect failed (%s), attempting reconnect", account.id, type(exc).__name__)
            try:
                client = await asyncio.wait_for(cm.reconnect(acc), timeout=CONNECT_TIMEOUT)
            except (AuthKeyDuplicatedError, AuthKeyUnregisteredError, UnauthorizedError):
                logger.error("discover_account(%s) auth failure on reconnect", account.id)
                raise
            except Exception as reconnect_exc:
                logger.error("discover_account(%s) reconnect also failed: %s", account.id, reconnect_exc)
                return
        if not client.is_connected() or not await asyncio.wait_for(client.is_user_authorized(), timeout=CONNECT_TIMEOUT):
            return
        await _maybe_update_identity(acc, client)
        monitor = StoryMonitor(client, acc, db)
        lookup = monitor._load_sets()
        await load_contacts_into(client, acc, lookup)
        monitor._lookup = lookup

        limit = int(cfg.get("search_results_max", 50))
        all_hashtags = cfg.get("hashtags") or [] if cfg.get("hashtags_enabled", True) else []
        all_locations = list(cfg.get("locations") or [])
        # Rotate through hashtags: search at most `hashtag_budget` per cycle.
        # With SEARCH_POSTS_MIN_INTERVAL=3.5s, each hashtag costs ~3.5s.
        # Aim to search ~30 hashtags per cycle (≈105s) so all hashtags are
        # covered in 2-3 cycles even with 100+ tags.
        hashtag_budget = max(10, min(100, len(all_hashtags) // 3 + 10))
        uid = account.user_id or 0
        if all_hashtags:
            h_offset = _hashtag_offset.get(uid, 0) % len(all_hashtags)
            hashtags = (all_hashtags[h_offset:] + all_hashtags[:h_offset])[:hashtag_budget]
            _hashtag_offset[uid] = (h_offset + hashtag_budget) % len(all_hashtags)
        else:
            hashtags = []
        # Same for locations: rotate through them with a budget to prevent
        # one user with thousands of venues from starving others.
        location_budget = max(10, min(50, len(all_locations) // 5 + 10))
        auto_locations: list[str] = []
        # When auto-add is enabled, rotate through ALL collected geo places,
        # searching at most ``searches_per_hour`` of them per cycle.
        if cfg.get("auto_add_places", True):
            from ..models import GeoPlace

            auto_budget = max(1, int(cfg.get("searches_per_hour", 10)))
            # Fetch only the venue identifiers (the table grows unboundedly;
            # pulling full ORM rows just to build a venue list is wasteful).
            existing_vids = {
                l[len("venue:"):] for l in all_locations if l.startswith("venue:")
            }
            if existing_vids:
                place_vids = (
                    db.query(GeoPlace.venue_id)
                    .filter(~GeoPlace.venue_id.in_(existing_vids), GeoPlace.venue_id.isnot(None))
                    .order_by(GeoPlace.id)
                    .all()
                )
                auto = [r[0] for r in place_vids]
            else:
                place_vids = (
                    db.query(GeoPlace.venue_id)
                    .filter(GeoPlace.venue_id.isnot(None))
                    .order_by(GeoPlace.id)
                    .all()
                )
                auto = [r[0] for r in place_vids]
            if auto:
                start = _auto_venue_offset.get(uid, 0) % len(auto)
                auto_locations = [f"venue:{vid}" for vid in (auto[start:] + auto[:start])[:auto_budget]]
                _auto_venue_offset[uid] = (start + auto_budget) % len(auto)
        # Rotate through manually-configured locations.
        if all_locations:
            l_offset = _location_offset.get(uid, 0) % len(all_locations)
            manual_locations = (all_locations[l_offset:] + all_locations[:l_offset])[:location_budget]
            _location_offset[uid] = (l_offset + location_budget) % len(all_locations)
        else:
            manual_locations = []

        # Geo-search from saved radius: find venues within the configured
        # radius of the saved center point and add them to the search list.
        geo_venues: list[str] = []
        # Read from legacy nested dict OR flattened top-level keys
        geo_search_cfg = cfg.get("geo_search") or {}
        geo_enabled = geo_search_cfg.get("enabled", False) or cfg.get("geo_search_enabled", False)
        geo_lat = geo_search_cfg.get("lat") or cfg.get("geo_search_lat")
        geo_lng = geo_search_cfg.get("lng") or cfg.get("geo_search_lng")
        geo_radius = float(geo_search_cfg.get("radius_km", 0) or cfg.get("geo_search_radius_km", 0) or 10)
        # Also enable geo if lat/lng are present (even if enabled flag was lost)
        if not geo_enabled and geo_lat is not None and geo_lng is not None:
            geo_enabled = True
        if geo_enabled and geo_lat is not None and geo_lng is not None:
            from ..models import GeoPlace
            import math
            _R = 6371.0
            c_lat = float(geo_lat)
            c_lng = float(geo_lng)
            c_radius = geo_radius
            geo_key = (c_lat, c_lng, c_radius)
            cached = _geo_radius_cache.get(uid)
            if cached and cached[0] == geo_key and (time.monotonic() - cached[1]) < GEO_RADIUS_CACHE_TTL:
                geo_venues = cached[2]
            else:
                # Bounding box (fast pre-filter)
                lat_margin = c_radius / 111.0 + 0.5
                lng_margin = c_radius / (111.0 * math.cos(math.radians(c_lat))) + 0.5
                candidates = (
                    db.query(GeoPlace)
                    .filter(
                        GeoPlace.lat.isnot(None),
                        GeoPlace.long.isnot(None),
                        GeoPlace.lat >= c_lat - lat_margin,
                        GeoPlace.lat <= c_lat + lat_margin,
                        GeoPlace.long >= c_lng - lng_margin,
                        GeoPlace.long <= c_lng + lng_margin,
                    )
                    .all()
                )
                geo_venues = []
                for p in candidates:
                    dlat = math.radians(p.lat - c_lat)
                    dlng = math.radians(p.long - c_lng)
                    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(c_lat)) * math.cos(math.radians(p.lat)) * math.sin(dlng / 2) ** 2
                    dist = _R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    if dist <= c_radius and p.venue_id:
                        geo_venues.append(f"venue:{p.venue_id}")
                _geo_radius_cache[uid] = (geo_key, time.monotonic(), geo_venues)
            logger.info("geo-search: found %d venues within %.1fkm of (%.4f, %.4f)", len(geo_venues), c_radius, c_lat, c_lng)

        # Apply budget to geo venues: rotate through them in batches
        # to avoid flooding Telegram with hundreds of requests per cycle.
        geo_budget = max(10, min(50, len(geo_venues) // 5 + 10)) if geo_venues else 0
        if geo_venues and geo_budget > 0:
            full_geo_count = len(geo_venues)
            g_offset = _geo_venue_offset.get(uid, 0) % full_geo_count
            geo_venues = (geo_venues[g_offset:] + geo_venues[:g_offset])[:geo_budget]
            _geo_venue_offset[uid] = (g_offset + geo_budget) % full_geo_count
            logger.info("geo-search: using %d/%d venues (budget=%d)", len(geo_venues), geo_budget, geo_budget)

        locations = manual_locations + auto_locations + geo_venues
        # Deduplicate across the three sources: auto excludes manually-listed
        # venues, but geo_venues overlaps with both, so one venue would
        # otherwise be searched up to three times in a single cycle.
        locations = _dedupe_locations(locations)
        # Give this account a fresh SearchPosts pacing budget for the cycle.
        discovery._reset_pacing(monitor)
        # Hashtags first: they reliably return results (venue searches are
        # noisy/empty in practice), so give them the budget before locations
        # consume it all.
        hashtag_processed = 0
        if hashtags:
            hashtag_processed = await discovery.search_hashtags(monitor, hashtags, limit)
        location_processed = 0
        if locations:
            location_processed = await discovery.search_locations(monitor, locations, limit)
        logger.info(
            "discovery: account %s cycle done — hashtags %d/%d (processed=%d), locations %d (processed=%d)",
            account.id, len(hashtags), hashtag_budget, hashtag_processed,
            len(locations), location_processed,
        )
    except AuthKeyDuplicatedError as exc:
        logger.error("discover_account(%s) AuthKeyDuplicatedError — session invalidated by IP change, marking AUTH_REQUIRED", account.id)
        db.close()
        try:
            await cm.mark_account_auth_required(account.id, drop_session=True)
        except Exception:
            pass
    except (AuthKeyUnregisteredError, UnauthorizedError) as exc:
        logger.error("discover_account(%s) session unregistered — marking AUTH_REQUIRED", account.id)
        db.close()
        try:
            await cm.mark_account_auth_required(account.id, drop_session=False)
        except Exception:
            pass
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


async def reconcile_orphaned_clients() -> int:
    """Drop cached Telegram clients whose account rows no longer exist.

    Deleted users/accounts (admin panel) are never picked again by
    ``run_once``/discovery, but the in-memory ``cm._clients`` cache keeps the
    account authorized on Telegram until a restart or VPN IP change. This
    releases the cached client + leftover session files so the phone number can
    be used by a fresh login right away.
    """
    ids = cm.cached_account_ids()
    if not ids:
        return 0
    db = SessionLocal()
    try:
        existing = {
            row[0]
            for row in db.query(TelegramAccount.id).filter(TelegramAccount.id.in_(ids)).all()
        }
    finally:
        db.close()
    dropped = 0
    for account_id in ids:
        if account_id not in existing:
            try:
                await cm.forget_account(account_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("forget_account(%s) failed: %s", account_id, exc)
            dropped += 1
    if dropped:
        logger.info("reconciled %d orphaned Telegram client(s)", dropped)
    return dropped


def main() -> None:
    import os

    logging.basicConfig(level=logging.INFO)
    from ..db import init_db

    init_db()  # ensure tables exist even if the API hasn't booted yet
    interval = float(os.environ.get("STORYWATCHER_SYNC_INTERVAL", "30"))
    asyncio.run(run_forever(interval=interval))


if __name__ == "__main__":
    main()