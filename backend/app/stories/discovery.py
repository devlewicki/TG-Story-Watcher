"""
Story Discovery: global search for stories via ``stories.SearchPosts``.

Telegram exposes global story search by **hashtag** or by a **geolocation media
area** (``stories.searchPosts``). This module runs those searches and feeds the
results through the same filter/queue pipeline as the regular monitor.

Note on geolocation: the API accepts a ``MediaArea`` built from a real venue
id in Telegram's internal (Foursquare-based) database (``MediaAreaVenue``).
Arbitrary geo points (``MediaAreaGeoPoint``) are rejected with
``HASHTAG_INVALID`` even with a real access hash. We therefore:

  - harvest ``MediaAreaVenue`` tags from every story we see into ``geo_places``
    so the panel offers a pickable list of real, searchable places;
  - resolve ``venue:<id>`` / place-title entries to such venues;
  - resolve ``city:<name>`` entries to a matching collected venue when
    possible, otherwise fall back to a hashtag search with the city name;
  - accept raw "lat,long" coordinates as a best-effort (may be rejected).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone

from telethon import errors, functions, types

from ..models import GeoPlace
from ..services import activity
from .monitor import StoryMonitor, _pid_of, collect_venues, resolve_authors

logger = logging.getLogger("storywatcher.discovery")

RESULT_LIMIT = 50

# Hard ceiling on any single Telegram RPC inside discovery. A half-open TCP
# through a dropped proxy tunnel would otherwise hang the await forever and
# starve every future discovery cycle.
RPC_TIMEOUT = 120.0

# --- SearchPosts pacing ---
# stories.searchPosts is one of Telegram's most aggressively rate-limited
# methods. Left unpaced, one discovery cycle fires ~70 venue/hashtag queries
# per account back-to-back and instantly trips the flood ceiling — Telegram
# then answers with empty pages instead of an error. Throttle RPCs per
# account: a minimum gap between calls and a hard budget per cycle. The
# scheduler's rotation offsets advance every cycle regardless, so venues we
# skip here simply come around again a few cycles later.
SEARCH_POSTS_MIN_INTERVAL = 6.0
SEARCH_POSTS_CYCLE_BUDGET = 30

_search_rpc_last: dict[int, float] = {}
_search_rpc_cycle_budget: dict[int, int] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _connected(monitor: StoryMonitor) -> bool:
    """Cheap local check that the Telethon client is still connected.

    Called before (and between) Telegram RPCs so that a VPN-level disconnect
    aborts the discovery cycle immediately instead of burning hundreds of
    failing ``SearchPosts`` requests ("Cannot send requests while
    disconnected") across the rest of the cycle.
    """
    try:
        return bool(monitor.client.is_connected())
    except Exception:  # noqa: BLE001
        return False


# Flood-hit counter per account. stories.searchPosts is aggressively
# rate-limited; the first FloodWaitError in a cycle is slept through (the
# search list keeps going), and only a second one within the same cycle stops
# the account's work. Allowed to decay across cycles via _reset_pacing.
_flood_hits: dict[int, int] = {}


def _reset_pacing(monitor: StoryMonitor) -> None:
    """Start a fresh pacing budget and flood-hit counter for this account."""
    _search_rpc_cycle_budget[monitor.account.id] = SEARCH_POSTS_CYCLE_BUDGET
    _flood_hits.pop(monitor.account.id, None)


def _search_slots_left(monitor: StoryMonitor) -> int:
    # Unset (e.g. when called directly) means a full budget: default it so a
    # bare search outside the scheduler loop still works.
    return _search_rpc_cycle_budget.get(monitor.account.id, SEARCH_POSTS_CYCLE_BUDGET)


async def _acquire_search_slot(monitor: StoryMonitor) -> bool:
    """Wait out the per-account interval and consume one SearchPosts slot.

    Returns False when this account's per-cycle budget is exhausted, in which
    case the caller should stop issuing further searches this cycle.
    """
    acc_id = monitor.account.id
    if _search_slots_left(monitor) <= 0:
        logger.info(
            "discovery: account %s SearchPosts budget exhausted — skipping rest of cycle",
            acc_id,
        )
        return False
    now = time.monotonic()
    last = _search_rpc_last.get(acc_id, 0.0)
    wait = SEARCH_POSTS_MIN_INTERVAL - (now - last)
    if wait > 0:
        await asyncio.sleep(wait)
    _search_rpc_last[acc_id] = time.monotonic()
    _search_rpc_cycle_budget[acc_id] = _search_slots_left(monitor) - 1
    return True


def _geo_point_from_text(text: str) -> types.GeoPoint | None:
    """Parse a 'lat,long' string into a GeoPoint, or None if not coordinates."""
    text = text.strip()
    if "," not in text:
        return None
    try:
        lat_s, long_s = text.split(",", 1)
        lat = float(lat_s.strip())
        long = float(long_s.strip())
        if not (-90 <= lat <= 90) or not (-180 <= long <= 180):
            return None
        return types.GeoPoint(long=long, lat=lat, access_hash=0)
    except ValueError:
        return None


def _geo_area(geo: types.GeoPoint) -> types.MediaArea:
    coords = types.MediaAreaCoordinates(x=0.5, y=0.5, w=1.0, h=1.0, rotation=0.0)
    return types.MediaAreaGeoPoint(coordinates=coords, geo=geo)


async def search_hashtags(
    monitor: StoryMonitor, hashtags: list[str], limit: int = RESULT_LIMIT
) -> int:
    """Search stories by hashtags and feed them into the monitor pipeline."""
    processed = 0
    for tag in hashtags:
        tag = tag.strip().lstrip("#")
        if not tag:
            continue
        # SearchPosts is heavily rate-limited: once the per-cycle budget runs
        # out, stop issuing further queries (rotation re-covers them later).
        if _search_slots_left(monitor) <= 0:
            break
        # VPN/client went away mid-cycle: stop rather than spam failing RPCs.
        if not _connected(monitor):
            logger.info("discovery: client disconnected — aborting hashtag search")
            break
        try:
            count = await _search_posts(monitor, hashtag=tag, limit=limit)
            processed += count
            # Only log real finds — per-search "0 stories" entries would flood
            # the activity feed (thousands of venues are searched per cycle).
            if count:
                activity.log(
                    f"Discovery hashtag #{tag}: {count} stories processed",
                    event_type="discovery_hashtag",
                    account_id=monitor.account.id,
                    metadata={"hashtag": tag, "processed": count},
                    db=monitor.db,
                )
        except errors.FloodWaitError as e:
            logger.warning("discovery #%s flood wait %ss", tag, e.seconds)
            activity.log(
                f"Discovery #{tag} flood wait {e.seconds}s",
                event_type="discovery_error",
                level="WARNING",
                account_id=monitor.account.id,
                db=monitor.db,
            )
            # Wait once and carry on with the next tag; only a second flood in
            # the same cycle stops the list — one transient wait must not
            # abort the whole account's work.
            _flood_hits[monitor.account.id] = _flood_hits.get(monitor.account.id, 0) + 1
            await asyncio.sleep(min(e.seconds, 30))
            if _flood_hits[monitor.account.id] >= 2:
                logger.info("discovery #%s: repeated flood — stopping hashtag search", tag)
                break
        except errors.UnauthorizedError:
            # Session was revoked server-side (account logged out). Re-raise so
            # the scheduler marks the account AUTH_REQUIRED instead of treating
            # every search as a transient failure.
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("discovery #%s failed: %s", tag, exc)
            activity.log(
                f"Discovery #{tag} failed: {exc}",
                event_type="discovery_error",
                level="ERROR",
                account_id=monitor.account.id,
                db=monitor.db,
            )
    return processed


async def search_locations(
    monitor: StoryMonitor, locations: list[str], limit: int = RESULT_LIMIT
) -> int:
    """Search stories by geolocation.

    Entries can be either:
      - a stored place name (matching a collected ``GeoPlace`` by title),
      - a raw venue id (``venue:4c45d722...``), or
      - ``lat,long`` coordinates (best effort; Telegram may reject these).
    """
    processed = 0
    for loc in locations:
        loc = loc.strip()
        if not loc:
            continue
        # SearchPosts is heavily rate-limited: once the per-cycle budget runs
        # out, stop issuing further queries (rotation re-covers them later).
        if _search_slots_left(monitor) <= 0:
            break
        # VPN/client went away mid-cycle: stop rather than spam failing RPCs.
        if not _connected(monitor):
            logger.info("discovery: client disconnected — aborting location search")
            break
        # Cities are resolved specially: try a collected venue with a matching
        # title first, otherwise fall back to a hashtag search with the city
        # name (Telegram rejects arbitrary geo points, see module docstring).
        if loc.lower().startswith("city:"):
            processed += await _search_city(monitor, loc[5:].strip(), limit)
            continue
        area = _area_for_location(monitor, loc)
        if area is None:
            logger.info("discovery location '%s' not resolvable; skipped", loc)
            activity.log(
                f"Discovery geo '{loc}': could not resolve geo-tag",
                event_type="discovery_error",
                level="WARNING",
                account_id=monitor.account.id,
                db=monitor.db,
            )
            continue
        try:
            count = await _search_posts(monitor, area=area, limit=limit)
            processed += count
            # Only log real finds (see search_hashtags note).
            if count:
                activity.log(
                    f"Discovery geo {loc}: {count} stories processed",
                    event_type="discovery_geo",
                    account_id=monitor.account.id,
                    metadata={"location": loc, "processed": count},
                    db=monitor.db,
                )
        except errors.FloodWaitError as e:
            logger.warning("discovery geo '%s' flood wait %ss", loc, e.seconds)
            activity.log(
                f"Discovery geo '{loc}' flood wait {e.seconds}s",
                event_type="discovery_error",
                level="WARNING",
                account_id=monitor.account.id,
                db=monitor.db,
            )
            # Wait once and carry on with the next venue; only a second flood
            # in the same cycle stops the list.
            _flood_hits[monitor.account.id] = _flood_hits.get(monitor.account.id, 0) + 1
            await asyncio.sleep(min(e.seconds, 30))
            if _flood_hits[monitor.account.id] >= 2:
                logger.info("discovery geo '%s': repeated flood — stopping location search", loc)
                break
        except errors.UnauthorizedError:
            # Session was revoked server-side (account logged out). Re-raise so
            # the scheduler marks the account AUTH_REQUIRED instead of treating
            # every search as a transient failure.
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("discovery geo '%s' failed: %s", loc, exc)
            activity.log(
                f"Discovery geo '{loc}' failed: {exc}",
                event_type="discovery_error",
                level="ERROR",
                account_id=monitor.account.id,
                db=monitor.db,
            )
    return processed


async def _search_city(monitor: StoryMonitor, city: str, limit: int) -> int:
    """Search stories for a city name.

    Preferred path: a collected venue whose title matches the city (a real
    geo search that Telegram accepts). Fallback: hashtag search with the city
    name (works reliably, e.g. #волхов), logged transparently.
    """
    if monitor.db is not None:
        place = (
            monitor.db.query(GeoPlace)
            .filter(GeoPlace.title.ilike(f"%{city}%"))
            .order_by(GeoPlace.id.desc())
            .first()
        )
        if place is not None and place.venue_id:
            area = _venue_area(
                types.GeoPoint(long=place.long or 0.0, lat=place.lat or 0.0, access_hash=0),
                place.title,
                place.address or "",
                place.venue_id,
            )
            try:
                count = await _search_posts(monitor, area=area, limit=limit)
                if count:
                    activity.log(
                        f"Город '{city}': {count} stories по месту '{place.title}'",
                        event_type="discovery_geo",
                        account_id=monitor.account.id,
                        metadata={"location": city, "place": place.title, "processed": count},
                        db=monitor.db,
                    )
                return count
            except errors.FloodWaitError as e:
                logger.warning("discovery geo '%s' flood wait %ss", city, e.seconds)
                _flood_hits[monitor.account.id] = _flood_hits.get(monitor.account.id, 0) + 1
                return 0
            except errors.UnauthorizedError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("discovery geo '%s' via place failed: %s", city, exc)

    tag = re.sub(r"[^\w\u0400-\u04FF]+", "", city).lower()
    if not tag:
        return 0
    try:
        count = await _search_posts(monitor, hashtag=tag, limit=limit)
        if count:
            activity.log(
                f"Город '{city}': гео-метка не найдена, поиск по хештегу #{tag} ({count})",
                event_type="discovery_geo",
                account_id=monitor.account.id,
                metadata={"location": city, "hashtag": tag, "processed": count},
                db=monitor.db,
            )
        return count
    except errors.FloodWaitError as e:
        logger.warning("discovery city '%s' flood wait %ss", city, e.seconds)
        _flood_hits[monitor.account.id] = _flood_hits.get(monitor.account.id, 0) + 1
        return 0
    except errors.UnauthorizedError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("discovery city '%s' hashtag search failed: %s", city, exc)
        activity.log(
            f"Город '{city}': поиск не удался: {exc}",
            event_type="discovery_error",
            level="ERROR",
            account_id=monitor.account.id,
            db=monitor.db,
        )
        return 0


def _area_for_location(monitor: StoryMonitor, loc: str) -> types.MediaArea | None:
    """Resolve a location string to a Telegram searchable MediaArea."""
    # 1) raw venue id
    if loc.startswith("venue:"):
        vid = loc[len("venue:"):].strip()
        if vid:
            place = None
            if monitor.db is not None:
                place = monitor.db.query(GeoPlace).filter_by(venue_id=vid).first()
            if place is not None:
                return _venue_area(
                    types.GeoPoint(long=place.long or 0.0, lat=place.lat or 0.0, access_hash=0),
                    place.title,
                    place.address or "",
                    vid,
                )
            return _venue_area(types.GeoPoint(long=0.0, lat=0.0, access_hash=0), "", "", vid)
    # 2) a stored place (title match)
    if monitor.db is not None:
        place = (
            monitor.db.query(GeoPlace)
            .filter(GeoPlace.title.ilike(f"%{loc}%"))
            .order_by(GeoPlace.id.desc())
            .first()
        )
        if place is not None and place.venue_id:
            geo = types.GeoPoint(
                long=place.long or 0.0, lat=place.lat or 0.0, access_hash=0
            )
            return _venue_area(geo, place.title, place.address or "", place.venue_id)
    # 3) coordinates best-effort
    geo = _geo_point_from_text(loc)
    if geo is not None:
        return _geo_area(geo)
    return None


def _venue_area(
    geo: types.GeoPoint, title: str, address: str, venue_id: str
) -> types.MediaAreaVenue:
    return types.MediaAreaVenue(
        coordinates=types.MediaAreaCoordinates(x=0.5, y=0.5, w=1.0, h=1.0, rotation=0.0),
        geo=geo,
        title=title or "Место",
        address=address,
        provider="foursquare",
        venue_id=venue_id,
        venue_type="",
    )


async def _search_posts(
    monitor: StoryMonitor,
    *,
    hashtag: str | None = None,
    area: types.MediaArea | None = None,
    limit: int = RESULT_LIMIT,
) -> int:
    """Run one stories.searchPosts query and ingest results. Returns processed count."""
    client = monitor.client
    offset = ""
    processed = 0
    pages = 0
    while True:
        if not _connected(monitor):
            logger.info("discovery: client disconnected — aborting pagination of current search")
            break
        if not await _acquire_search_slot(monitor):
            break
        pages += 1
        # Bound pagination by pages: expired stories never count toward
        # ``processed``, so a processed-based cap would walk huge hashtags
        # (e.g. #спб has thousands of mostly-expired items) for minutes.
        if pages > 5:
            break
        try:
            res = await asyncio.wait_for(
                client(
                    functions.stories.SearchPostsRequest(
                        offset=offset,
                        limit=limit,
                        hashtag=hashtag,
                        area=area,
                    )
                ),
                timeout=RPC_TIMEOUT,
            )
        except errors.FloodWaitError:
            # Propagate so the per-tag handler can wait it out and continue
            # with the next hashtag/location instead of dropping them.
            raise
        except Exception as exc:  # noqa: BLE001
            # Transient API/transport error: stop this pagination loop but keep
            # whatever was already processed. The next cycle retries the whole
            # search.
            logger.warning(
                "search_posts failed (hashtag=%s area=%s): %s",
                hashtag or "", bool(area), exc,
            )
            break
        stories = getattr(res, "stories", []) or []
        if not stories:
            break

        # Merge users/chats returned with the results so author info is cheap.
        peer_cache: dict[int, dict] = {}
        for u in getattr(res, "users", []) or []:
            pid = _pid_of(u)
            if pid is not None:
                peer_cache.setdefault(pid, {}).update(_user_info(u))
        for c in getattr(res, "chats", []) or []:
            pid = _pid_of(c)
            if pid is not None:
                peer_cache.setdefault(pid, {}).update(_user_info(c))

        missing: set[int] = set()
        for fs in stories:
            peer_id = _pid_of(getattr(fs, "peer", None))
            story = getattr(fs, "story", None)
            if peer_id is None or story is None:
                continue
            if peer_id not in peer_cache:
                missing.add(peer_id)
        details = await resolve_authors(client, missing)
        for pid, d in details.items():
            peer_cache.setdefault(pid, {}).update(d)

        for fs in stories:
            peer_id = _pid_of(getattr(fs, "peer", None))
            story = getattr(fs, "story", None)
            if peer_id is None or story is None:
                continue
            info = peer_cache.get(peer_id, {})
            info.setdefault("published_at", getattr(story, "date", None))
            info.setdefault("expires_at", getattr(story, "expire_date", None))
            _, verdict, _ = monitor.ingest_story(
                peer_id,
                story.id,
                info,
                source=f"discovery:{hashtag or 'geo'}",
                rule_name=f"discovery:{hashtag or 'geo'}",
            )
            if verdict in ("enqueued", "already", "skipped"):
                processed += 1

        # Harvest venue tags from the returned stories so the geo-place list
        # grows from real places Telegram knows about.
        try:
            collect_venues(monitor.db, stories)
        except Exception as exc:  # noqa: BLE001
            logger.warning("collect_venues failed: %s", exc)

        offset = getattr(res, "next_offset", None)
        if not offset:
            break
        # Safety cap per search.
        if processed >= limit * 4:
            break

    return processed


def _user_info(ent) -> dict:
    return {
        "username": getattr(ent, "username", None),
        "first_name": getattr(ent, "first_name", None),
        "last_name": getattr(ent, "last_name", None),
        "is_channel": isinstance(ent, (types.Channel, types.Chat)),
        "is_group": isinstance(ent, (types.Channel, types.Chat)) and bool(
            getattr(ent, "megagroup", False)
        ),
        "is_bot": bool(getattr(ent, "bot", False)),
        "deleted": False,
    }