"""Queue processor: takes due StoryQueue entries and performs story views.

This is the heart of the automation. It is used both by the background worker
(``app.workers.queue_worker``) and can be triggered on-demand via the API.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from telethon import errors
from telethon import functions
from telethon import types

# Telethon <1.40 doesn't have Story*Error classes; guard against AttributeError
# at except-evaluation time — a missing class there crashes the whole handler.
_StoryIdInvalidError = getattr(errors, "StoryIdInvalidError", type("_Missing", (Exception,), {}))
_StoryExpiredError = getattr(errors, "StoryExpiredError", type("_Missing", (Exception,), {}))

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
            tz_name = SettingsService(db, account.user_id).get("general").get("timezone", "UTC")
            try:
                user_tz = ZoneInfo(tz_name)
            except Exception:
                user_tz = ZoneInfo("UTC")
            local_now = _now().astimezone(user_tz)
            day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
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

    peer = await _resolve_peer(client, story.peer_id)
    if peer is None:
        queue_item.status = "FAILED"
        queue_item.error = "peer not found"
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "FAILED", "error": queue_item.error}

    try:
        # Increment the story view counter (the supported signal that a
        # story was watched), using the documented user-side MTProto method.
        await client(functions.stories.IncrementStoryViewsRequest(peer, [story.telegram_story_id]))
    except errors.FloodWaitError as e:
        queue_item.status = "FAILED"
        queue_item.error = f"flood_wait {e.seconds}s"
        queue_item.completed_at = _now()
        db.commit()
        return {"status": "FAILED", "error": queue_item.error, "flood_wait": e.seconds}
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
            await client(
                functions.stories.SendReactionRequest(
                    peer=peer,
                    story_id=story.telegram_story_id,
                    reaction=types.ReactionEmoji(emoticon=like_emoji),
                )
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
    """Return a peer for the given id (raw id). Fall back to the raw id."""
    try:
        return await client.get_input_entity(peer_id)
    except Exception:  # noqa: BLE001
        return peer_id