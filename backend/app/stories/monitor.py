from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from telethon import functions, types

from ..filters.engine import AuthorInfo, FilterEngine
from ..models import (
    ActivityLog,
    BlacklistEntry,
    GeoPlace,
    Story,
    StoryQueue,
    TelegramAccount,
    WhitelistEntry,
)
from ..services import activity
from ..services.settings_service import SettingsService
from ..telegram import client_manager as cm

logger = logging.getLogger("storywatcher.stories")


def datetime_from_tl(dt) -> datetime | None:
    """Normalize Telegram date values (datetime, unix int/float, TL date) to UTC."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        # Telethon returns story dates as aware Python datetimes; keep as-is.
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if isinstance(dt, (int, float)):
        return datetime.fromtimestamp(int(dt), tz=timezone.utc)
    # Legacy custom TL date objects exposing ``.ts``.
    ts = getattr(dt, "ts", None)
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def _peer_id(peer) -> int | None:
    for attr in ("channel_id", "user_id", "chat_id"):
        if hasattr(peer, attr) and getattr(peer, attr):
            return getattr(peer, attr)
    return getattr(peer, "id", None)


async def resolve_authors(
    client, peer_ids: set[int]
) -> dict[int, dict]:
    """Fetch entity info for the given peer ids. Returns {peer_id: info_dict}."""
    result: dict[int, dict] = {}
    if not peer_ids:
        return result
    try:
        entities = await client.get_entity(peer_ids)
        if not isinstance(entities, list):
            entities = [entities]
        for ent in entities:
            pid = _peer_id(ent)
            if pid is None:
                continue
            result[pid] = {
                "username": getattr(ent, "username", None),
                "first_name": getattr(ent, "first_name", None),
                "last_name": getattr(ent, "last_name", None),
                "is_channel": isinstance(ent, (types.Channel, types.Chat)),
                "is_group": isinstance(ent, (types.Channel, types.Chat)) and bool(getattr(ent, "megagroup", False)),
                "is_bot": bool(getattr(ent, "bot", False)),
                "deleted": False,
                "username_set": True,
            }
    except Exception as exc:  # noqa: BLE001  PeerNotFound etc.
        logger.debug("resolve_authors partial failure: %s", exc)
    return result


class StoryMonitor:
    def __init__(self, client, account: TelegramAccount, db: Session):
        self.client = client
        self.account = account
        self.db = db
        self._skipped: set[tuple[int, int]] | None = None

    # ---- filtering helpers ----
    def _load_sets(self):
        s = SettingsService(self.db, self.account.user_id)
        return FiltersLookup.load(self.db, self.account.id, s)

    def _load_skipped_set(self) -> set[tuple[int, int]]:
        """Distinct (peer_id, story_id) pairs already logged as skipped (24h).

        Skipped stories are not stored in the DB, so without this every sync
        would re-log the same skip for as long as the story stays active
        (up to 24h), inflating the "filtered" counter with duplicates.
        """
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        rows = (
            self.db.query(ActivityLog.meta_json)
            .filter(
                ActivityLog.event_type == "story_skipped",
                ActivityLog.account_id == self.account.id,
                ActivityLog.created_at >= since,
            )
            .all()
        )
        out: set[tuple[int, int]] = set()
        for (raw,) in rows:
            try:
                meta = json.loads(raw) if raw else {}
            except (ValueError, TypeError):
                continue
            pid, sid = meta.get("peer_id"), meta.get("story_id")
            if pid is not None and sid is not None:
                out.add((int(pid), int(sid)))
        return out

    def build_engine(self):
        s = SettingsService(self.db, self.account.user_id)
        # Reuse a lookup that already has contacts populated (set by the
        # scheduler before the burst sync); otherwise load a fresh one.
        fl = getattr(self, "_lookup", None)
        if fl is None or not hasattr(fl, "contact_peers"):
            fl = FiltersLookup.load(self.db, self.account.id, s)
            self._lookup = fl
        filters = s.get("filters")
        return FilterEngine(
            filters,
            fl.wl_peers,
            fl.bl_peers,
            fl.wl_users,
            fl.bl_users,
        ), fl

    def author_info(self, peer_id: int, info: dict, fl) -> AuthorInfo:
        username = info.get("username")
        return AuthorInfo(
            account_id=self.account.id,
            peer_id=peer_id,
            username=username,
            first_name=info.get("first_name"),
            last_name=info.get("last_name"),
            is_contact=peer_id in fl.contact_peers,
            is_mutual=peer_id in fl.mutual_peers,
            is_channel=info.get("is_channel", False),
            is_group=info.get("is_group", False),
            is_bot=info.get("is_bot", False),
            is_deleted=info.get("deleted", False),
            in_whitelist=peer_id in fl.wl_peers or (username or "").lower() in fl.wl_users,
            in_blacklist=peer_id in fl.bl_peers or (username or "").lower() in fl.bl_users,
        )

    # ---- ingestion ----
    def ingest_story(
        self,
        peer_id: int,
        story_id: int,
        info: dict,
        *,
        source: str = "monitor",
        rule_name: str | None = None,
    ) -> tuple[Story | None, str | None, str | None]:
        """Check, store, evaluate and (if passed) enqueue a single story.

        Returns (story, verdict, reason): verdict is one of "enqueued",
        "already", "skipped" (filtered out), "expired".
        """
        engine, lookup = self.build_engine()
        self._lookup = lookup
        author = self.author_info(peer_id, info, lookup)
        result = engine.evaluate(author)

        existing = (
            self.db.query(Story)
            .filter_by(account_id=self.account.id, peer_id=peer_id, telegram_story_id=story_id)
            .first()
        )

        if existing is not None:
            # Ensure it's not already queued/viewed.
            queued = (
                self.db.query(StoryQueue)
                .filter_by(account_id=self.account.id, story_id=existing.id)
                .filter(StoryQueue.status.notin_(["CANCELLED"]))
                .first()
            )
            if queued is not None:
                return existing, "already", "already in queue"
            if existing.id is None:
                pass
            # Re-evaluate: allow queueing if it passed and not yet processed.
            if not result.passed:
                return existing, "skipped", result.reason
            self._enqueue(existing, result.rule_match)
            return existing, "enqueued", None

        if not result.passed:
            # Log each skip only once per story; otherwise the same active
            # story would be re-logged on every sync cycle (they are not stored
            # in the DB, so there is no existing record to dedupe against).
            key = (peer_id, story_id)
            if self._skipped is None:
                self._skipped = self._load_skipped_set()
            if key not in self._skipped:
                activity.log(
                    f"Story skipped: peer={peer_id} story={story_id} — {result.reason}",
                    event_type="story_skipped",
                    account_id=self.account.id,
                    metadata={"peer_id": peer_id, "story_id": story_id, "reason": result.reason},
                    db=self.db,
                )
                self._skipped.add(key)
            return None, "skipped", result.reason

        story = self._store_story(peer_id, story_id, info, source)
        if story is None:
            return None, "expired", "story expired"
        self._enqueue(story, result.rule_match, source=source, rule_name=rule_name)
        return story, "enqueued", None

    def _store_story(self, peer_id: int, story_id: int, info: dict, source: str) -> Story | None:
        # Expired histories carry no data; skip storing.
        published = datetime_from_tl(info.get("published_at"))
        expires = datetime_from_tl(info.get("expires_at"))
        now = datetime.now(timezone.utc)
        if expires is not None and expires < now:
            return None
        story = Story(
            account_id=self.account.id,
            peer_id=peer_id,
            telegram_story_id=story_id,
            author_username=info.get("username"),
            author_name=info.get("first_name") or info.get("username"),
            source=source,
            published_at=published,
            expires_at=expires,
            raw_data=json.dumps(info, default=str),
        )
        self.db.add(story)
        self.db.flush()
        return story

    def _enqueue(self, story: Story, rule_match: str | None, source: str = "monitor", rule_name: str | None = None) -> None:
        existing = (
            self.db.query(StoryQueue)
            .filter_by(account_id=self.account.id, story_id=story.id)
            .first()
        )
        if existing is not None:
            return
        s = SettingsService(self.db, self.account.user_id)
        min_delay = s.get("view").get("min_delay", 20)
        max_delay = s.get("view").get("max_delay", 120)
        import random

        delay = random.randint(int(min_delay), max(int(max_delay), int(min_delay)))
        from datetime import timedelta

        scheduled = datetime.now(timezone.utc) + timedelta(seconds=delay)
        entry = StoryQueue(
            account_id=self.account.id,
            story_id=story.id,
            status="PENDING",
            priority=1,
            scheduled_at=scheduled,
        )
        self.db.add(entry)
        activity.log(
            f"Story queued: peer={story.peer_id} story={story.telegram_story_id} "
            f"(delay {delay}s)"
            + (f" rule={rule_name}" if rule_name else ""),
            event_type="story_queued",
            account_id=self.account.id,
            metadata={
                "peer_id": story.peer_id,
                "story_id": story.telegram_story_id,
                "delay": delay,
                "rule": rule_name,
            },
            db=self.db,
        )
        self.db.commit()

    # ---- fetching available stories (burst fetch) ----
    async def fetch_available(self, resync: bool = True) -> int:
        peer_cache: dict[int, dict] = {}
        processed = 0
        state = None
        first = True
        while True:
            try:
                res = await self.client(
                    functions.stories.GetAllStoriesRequest(
                        next=not first,
                        state=state,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("getAllStories failed: %s", exc)
                activity.log(
                    f"getAllStories failed: {exc}",
                    event_type="api_error",
                    level="ERROR",
                    account_id=self.account.id,
                    db=self.db,
                )
                break

            # Stories come in three shapes across Telegram layers:
            #   - legacy wrapped items with ``.story`` and ``.peer``
            #   - AllStories.peer_stories entries (each PeerStories carries the
            #     author in ``.peer`` and the items as a plain list in ``.stories``)
            #   - already-flat StoryItem-like dicts
            stories = getattr(res, "stories", None)
            if stories is None:
                fetched = []
                for ps in getattr(res, "peer_stories", []) or []:
                    inner = getattr(ps, "stories", None)
                    wraps = inner if isinstance(inner, list) else getattr(inner, "stories", inner)
                    if not isinstance(wraps, list):
                        wraps = [wraps] if wraps is not None else []
                    # Attach the owning peer (PeerStories.peer) to every item so
                    # extract_story can resolve the author later.
                    pid = _pid_of(getattr(ps, "peer", None))
                    if pid is None:
                        pid = getattr(ps, "peer_id", None)
                    if pid is not None:
                        pid = int(pid)
                    for w in wraps:
                        if pid is not None:
                            _attach_peer(w, pid)
                        fetched.append(w)
                stories = fetched

            if not stories:
                break

            fetched_peers: set[int] = set()
            for s in stories:
                peer_id, story_id, info = extract_story(s)
                if peer_id is None or story_id is None:
                    continue
                fetched_peers.add(peer_id)
                info_cache = peer_cache.setdefault(peer_id, {})
                _merge_info(info_cache, info)

            # Merge users/chats that Telegram returns alongside the stories so
            # we don't have to re-resolve every peer over the network.
            for u in getattr(res, "users", []) or []:
                pid = _peer_id(u)
                if pid is not None:
                    peer_cache.setdefault(pid, {}).update(_base_info(u))
            for c in getattr(res, "chats", []) or []:
                pid = _peer_id(c)
                if pid is not None:
                    peer_cache.setdefault(pid, {}).update(_base_info(c))

            # Resolve entity meta for peers still missing details.
            missing = {
                p for p in fetched_peers if not peer_cache.get(p, {}).get("username_set")
            }
            details = await resolve_authors(self.client, {p for p in missing if p})
            for pid, d in details.items():
                peer_cache.setdefault(pid, {}).update(d)

            for s in stories:
                peer_id, story_id, info = extract_story(s)
                if peer_id is None or story_id is None:
                    continue
                _, verdict, _ = self.ingest_story(
                    peer_id, story_id, peer_cache.get(peer_id, {}), source="monitor"
                )
                if verdict in ("enqueued", "already", "skipped"):
                    processed += 1

            # Harvest venue tags from the feed so the geo-place list grows
            # without relying on global discovery alone.
            try:
                collect_venues(self.db, stories)
            except Exception as exc:  # noqa: BLE001
                logger.warning("collect_venues failed: %s", exc)

            state = getattr(res, "state", None)
            first = False
            if not getattr(res, "has_more", False):
                break
            if state is None:
                break
            # Safety cap against pathological pagination loops.
            if processed > 5000:
                break

        activity.log(
            f"Fetched available stories (processed={processed})",
            event_type="fetch_available",
            account_id=self.account.id,
            db=self.db,
        )
        return processed


def _pid_of(peer) -> int | None:
    """Best-effort raw entity id from a Peer/InputPeer/user-like object."""
    if peer is None:
        return None
    if isinstance(peer, (int, str)):
        return int(peer)
    return _peer_id(peer)


def _story_peer(item) -> int | None:
    """Determine the author peer id for a StoryItem-like object."""
    # 1) explicit peer attribute (attached by wrapper / update)
    pid = _pid_of(getattr(item, "peer", None))
    if pid is not None:
        return pid
    pid = getattr(item, "peer_id", None)
    if pid is not None:
        return int(pid)
    # 2) attached author flag set when unwrapping peer_stories blocks
    attached = getattr(item, "_peer_id", None)
    if attached is not None:
        return int(attached)
    # 3) StoryItem.from_id Point (for channels, this is the channel itself)
    frm = getattr(item, "from_id", None)
    if frm is not None:
        return _pid_of(frm)
    return None


def extract_story(item) -> tuple[int | None, int | None, dict]:
    """Extract (peer_id, story_id, info) from a reasonable set of Telegram story shapes."""
    if isinstance(item, types.StoryItem):
        return _story_peer(item), item.id, {
            "published_at": getattr(item, "date", None),
            "expires_at": getattr(item, "expire_date", None),
        }
    # StoryItem as "story" attribute in wrapped structures.
    story = getattr(item, "story", None)
    if isinstance(story, types.StoryItem):
        pid = _pid_of(getattr(item, "peer", None)) or getattr(item, "peer_id", None) or _story_peer(story)
        if pid is not None:
            pid = int(pid)
        return pid, story.id, {
            "published_at": getattr(story, "date", None),
            "expires_at": getattr(story, "expire_date", None),
        }
    # Flat dict-like items.
    if getattr(item, "id", None) is not None:
        return _story_peer(item), item.id, {
            "published_at": getattr(item, "date", None),
            "expires_at": getattr(item, "expire_date", None),
        }
    return None, None, {}


def _attach_peer(item, peer_id: int) -> None:
    """Tag a wrapped StoryItem with its owning peer id when available."""
    try:
        item._peer_id = peer_id
    except Exception:  # noqa: BLE001
        pass


def _base_info(ent) -> dict:
    """Basic entity info for a User/Chat/Channel object fetched alongside stories."""
    return {
        "username": getattr(ent, "username", None),
        "first_name": getattr(ent, "first_name", None),
        "last_name": getattr(ent, "last_name", None),
        "is_channel": isinstance(ent, (types.Channel, types.Chat)),
        "is_group": isinstance(ent, (types.Channel, types.Chat)) and bool(getattr(ent, "megagroup", False)),
        "is_bot": bool(getattr(ent, "bot", False)),
        "deleted": False,
        "username_set": True,
    }


def _merge_info(target: dict, extra: dict) -> None:
    for k, v in extra.items():
        target.setdefault(k, v)


def collect_venues(db: Session, items: list) -> int:
    """Collect Foursquare venue tags from story media areas into ``geo_places``.

    Telegram's story search by location (``stories.searchPosts``) only accepts a
    ``MediaAreaVenue`` built from a real venue id in Telegram's internal
    (Foursquare-based) database. We harvest those tags from every story we see
    (both the account feed and global discovery), so the panel can offer a
    pickable list of places that actually work for geo search.

    Returns the number of newly collected places.
    """
    added = 0
    seen: set[str] = set()
    for item in items:
        story = getattr(item, "story", None)
        if not isinstance(story, types.StoryItem):
            story = item if isinstance(item, types.StoryItem) else None
        if story is None:
            continue
        for area in getattr(story, "media_areas", None) or []:
            if not isinstance(area, types.MediaAreaVenue):
                continue
            vid = (getattr(area, "venue_id", "") or "").strip()
            if not vid or vid in seen:
                continue
            seen.add(vid)
            existing = db.query(GeoPlace).filter_by(venue_id=vid).first()
            if existing is not None:
                continue
            geo = getattr(area, "geo", None)
            db.add(
                GeoPlace(
                    venue_id=vid,
                    title=(getattr(area, "title", None) or "Место").strip()[:255],
                    address=getattr(area, "address", None) or None,
                    provider=(getattr(area, "provider", None) or "foursquare"),
                    lat=getattr(geo, "lat", None) if geo else None,
                    long=getattr(geo, "long", None) if geo else None,
                )
            )
            added += 1
    if added:
        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001  unique-violation race
            db.rollback()
            logger.warning("collect_venues commit failed (race): %s", exc)
            return 0
        logger.info("collected %d new geo place(s)", added)
    return added


class FiltersLookup:
    @classmethod
    def load(cls, db: Session, account_id: int, settings_service: SettingsService):
        self = cls()
        wl = db.query(WhitelistEntry).filter_by(account_id=account_id).all()
        bl = db.query(BlacklistEntry).filter_by(account_id=account_id).all()
        self.wl_peers = {e.peer_id for e in wl if e.peer_id}
        self.wl_users = {u.lower() for e in wl if (u := (e.username or ""))}
        self.bl_peers = {e.peer_id for e in bl if e.peer_id}
        self.bl_users = {u.lower() for e in bl if (u := (e.username or ""))}
        # Contacts are fetched on demand and cached by the monitor.
        self.contact_peers: set[int] = set()
        self.mutual_peers: set[int] = set()
        return self


# Per-process cache of the account contact set, refreshed every _CONTACTS_TTL
# seconds. GetContacts returns the whole list on every call (here: 800+ entries)
# and is easy to flood-wait, yet the worker calls it on every sync and discovery
# cycle — so cache it and only re-fetch when stale.
_CONTACTS_TTL = 1800.0  # 30 minutes — GetContacts triggers FloodWait
_contacts_cache: dict[int, tuple[float, set[int], set[int]]] = {}


async def load_contacts_into(client, account: TelegramAccount, lookup: FiltersLookup) -> None:
    """Populate the lookup's contact sets (cached per process).

    Raises on failure: callers abort the cycle instead of silently ingesting
    with an empty contact set, which would treat every contact as "unknown"
    and bypass the filter.
    """
    cached = _contacts_cache.get(account.id)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _CONTACTS_TTL:
        _, contact_ids, mutual_ids = cached
        lookup.contact_peers = set(contact_ids)
        lookup.mutual_peers = set(mutual_ids)
        return
    contacts = await client(functions.contacts.GetContactsRequest(hash=0))
    contact_ids: set[int] = set()
    mutual_ids: set[int] = set()
    for c in getattr(contacts, "users", []) or []:
        pid = _peer_id(c)
        if pid is None:
            continue
        contact_ids.add(pid)
        if bool(getattr(c, "mutual", False)):
            mutual_ids.add(pid)
    _contacts_cache[account.id] = (now, contact_ids, mutual_ids)
    lookup.contact_peers = contact_ids
    lookup.mutual_peers = mutual_ids