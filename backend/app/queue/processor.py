"""Queue processor: takes due StoryQueue entries and performs story views.

This is the heart of the automation. It is used both by the background worker
(``app.workers.queue_worker``) and can be triggered on-demand via the API.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from telethon import errors
from telethon import functions
from telethon import types

# Telethon <1.40 doesn't have Story*Error classes; guard against AttributeError
# at except-evaluation time — a missing class there crashes the whole handler.
_StoryIdInvalidError = getattr(errors, "StoryIdInvalidError", type("_Missing", (Exception,), {}))
_StoryExpiredError = getattr(errors, "StoryExpiredError", type("_Missing", (Exception,), {}))

# Hard timeout for a single Telegram RPC so a wedged request cannot block the
# queue drain forever (K-01/K-02). On timeout the item is requeued and the
# worker reconnects the client.
RPC_TIMEOUT = 45

from ..models import (
    Story,
    StoryQueue,
    StoryView,
    TelegramAccount,
)
from ..services import activity
from ..services.settings_service import SettingsService

logger = logging.getLogger("storywatcher.queue")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def process_queue_item(
    client,
    account: TelegramAccount,
    queue_item: StoryQueue,
    db: Session,
    *,
    patient: bool = True,
) -> dict:
    """Process a single queue item. Returns a result dict.

    Handles: already-processed guard, active check, expiration, view action,
    rate limit bookkeeping done by the caller (the worker) before invoking.
    """
    story = db.get(Story, queue_item.story_id) if queue_item.story_id else None
    if story is None:
        queue_item.status = "FAILED"
        queue_item.error = "story record missing"
        db.commit()
        return {"status": "FAILED", "error": queue_item.error}

    # Guard against re-processing.
    already = (
        db.query(StoryView)
        .filter_by(account_id=account.id, peer_id=story.peer_id, telegram_story_id=story.telegram_story_id)
        .first()
    )
    if already is not None:
        queue_item.status = "VIEWED"
        queue_item.error = "already viewed"
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "VIEWED", "error": "already viewed"}

    # Re-check the per-author daily limit immediately before the Telegram call.
    # Queue-time checks cannot cover items queued before a setting change or
    # multiple workers racing to process the same author.
    try:
        view_cfg = SettingsService(db, account.user_id).get("view")
        max_per_user = int(view_cfg.get("max_stories_per_user_per_day", 3))
        if max_per_user > 0:
            # Day boundary is always Moscow time (app-wide policy).
            from ..api.timezone import user_today
            day_start = user_today(db, account.user_id)
            viewed_today = (
                db.query(StoryView)
                .join(TelegramAccount, StoryView.account_id == TelegramAccount.id)
                .filter(
                    TelegramAccount.user_id == account.user_id,
                    StoryView.peer_id == story.peer_id,
                    StoryView.viewed_at >= day_start,
                )
                .count()
            )
            active_for_peer = (
                db.query(StoryQueue)
                .join(Story, Story.id == StoryQueue.story_id)
                .join(TelegramAccount, StoryQueue.account_id == TelegramAccount.id)
                .filter(
                    TelegramAccount.user_id == account.user_id,
                    Story.peer_id == story.peer_id,
                    StoryQueue.status.in_(["PENDING", "WAITING_DELAY", "PROCESSING"]),
                    StoryQueue.id != queue_item.id,
                )
                .count()
            )
            if viewed_today + active_for_peer >= max_per_user:
                queue_item.status = "SKIPPED"
                queue_item.error = f"daily author limit reached ({viewed_today}/{max_per_user})"
                queue_item.completed_at = _now()
                activity.log(
                    f"Story skipped: peer={story.peer_id} — {queue_item.error}",
                    event_type="story_skipped",
                    account_id=account.id,
                    metadata={"peer_id": story.peer_id, "story_id": story.telegram_story_id, "reason": "daily limit"},
                    db=db,
                )
                db.commit()
                return {"status": "SKIPPED", "error": queue_item.error}
    except Exception as exc:  # noqa: BLE001
        logger.warning("per-author daily limit check failed: %s", exc)

    queue_item.status = "PROCESSING"
    queue_item.started_at = _now()
    queue_item.attempts += 1
    db.commit()

    peer = None
    try:
        peer = await asyncio.wait_for(_resolve_peer(client, story.peer_id), timeout=RPC_TIMEOUT)
    except asyncio.TimeoutError:
        queue_item.status = "FAILED"
        queue_item.error = f"peer resolve timed out (peer={story.peer_id})"
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "FAILED", "error": queue_item.error, "reconnect": True}
    except Exception as exc:  # noqa: BLE001
        queue_item.status = "FAILED"
        queue_item.error = f"peer not found: {exc}"
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "FAILED", "error": queue_item.error}
    if peer is None:
        queue_item.status = "FAILED"
        queue_item.error = "peer not found"
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "FAILED", "error": queue_item.error}

    try:
        # Increment the story view counter (the supported signal that a
        # story was watched), using the documented user-side MTProto method.
        await asyncio.wait_for(
            client(functions.stories.IncrementStoryViewsRequest(peer, [story.telegram_story_id])),
            timeout=RPC_TIMEOUT,
        )
    except errors.FloodWaitError as e:
        queue_item.status = "FAILED"
        queue_item.error = f"flood_wait {e.seconds}s"
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "FAILED", "error": queue_item.error, "flood_wait": e.seconds}
    except asyncio.TimeoutError:
        queue_item.status = "FAILED"
        queue_item.error = "view request timed out"
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "FAILED", "error": queue_item.error, "reconnect": True}
    except _StoryIdInvalidError:
        queue_item.status = "EXPIRED"
        queue_item.error = "story not found (expired or deleted)"
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "EXPIRED", "error": queue_item.error}
    except _StoryExpiredError:
        queue_item.status = "EXPIRED"
        queue_item.error = "story expired"
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "EXPIRED", "error": queue_item.error}
    except Exception as exc:  # noqa: BLE001
        queue_item.status = "FAILED"
        queue_item.error = str(exc)[:500]
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "FAILED", "error": queue_item.error}

    # Optional auto-like: react to the story with the configured emoji.
    # The view already succeeded; a failed reaction must not fail the item.
    like_emoji = None
    try:
        view_cfg = SettingsService(db, account.user_id).get("view")
        if view_cfg.get("auto_like"):
            like_emoji = (view_cfg.get("like_emoji") or "👍").strip() or "👍"
    except Exception as exc:  # noqa: BLE001
        logger.warning("read view settings failed: %s", exc)
    if like_emoji:
        try:
            await asyncio.wait_for(
                client(
                    functions.stories.SendReactionRequest(
                        peer=peer,
                        story_id=story.telegram_story_id,
                        reaction=types.ReactionEmoji(emoticon=like_emoji),
                    )
                ),
                timeout=RPC_TIMEOUT,
            )
            activity.log(
                f"Story liked: peer={story.peer_id} story={story.telegram_story_id} ({like_emoji})",
                event_type="story_liked",
                account_id=account.id,
                metadata={"peer_id": story.peer_id, "story_id": story.telegram_story_id, "emoji": like_emoji},
                db=db,
            )
        except errors.FloodWaitError as e:
            logger.warning("story like flood wait %ss (peer=%s story=%s)", e.seconds, story.peer_id, story.telegram_story_id)
        except asyncio.TimeoutError:
            logger.warning("story like timed out (peer=%s story=%s)", story.peer_id, story.telegram_story_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("story like failed (peer=%s story=%s): %s", story.peer_id, story.telegram_story_id, exc)

    queue_item.status = "VIEWED"
    queue_item.completed_at = _now()
    db.add(
        StoryView(
            account_id=account.id,
            story_id=story.id,
            peer_id=story.peer_id,
            telegram_story_id=story.telegram_story_id,
            source=story.source,
            status="VIEWED",
        )
    )
    activity.log(
        f"Story viewed: peer={story.peer_id} story={story.telegram_story_id}",
        event_type="story_viewed",
        account_id=account.id,
        metadata={"peer_id": story.peer_id, "story_id": story.telegram_story_id},
        db=db,
    )
    db.commit()
    return {"status": "VIEWED"}


async def _resolve_peer(client, peer_id: int):
    """Resolve a peer id to an InputPeer object.

    Raises on failure — the caller marks the queue item FAILED with the error.
    Previously this fell back to returning the raw int, which produced a
    cryptic TypeError when passed to IncrementStoryViewsRequest.
    """
    peer = await client.get_input_entity(peer_id)
    if peer is None:
        raise RuntimeError(f"could not resolve peer id {peer_id}")
    return peer