from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from telethon import functions, types

from ..models import Story, StoryReactionStat, StoryStatsSnapshot, StoryViewer, TelegramAccount

logger = logging.getLogger("storywatcher.analytics")


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, int):
        return datetime.fromtimestamp(value, timezone.utc)
    return None


def _reaction_key(reaction: Any) -> str:
    if isinstance(reaction, types.ReactionEmoji):
        return reaction.emoticon
    if isinstance(reaction, types.ReactionCustomEmoji):
        return f"custom:{reaction.document_id}"
    return type(reaction).__name__


def _attr(obj: Any, *names: str, default=None):
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


async def _call(client, request, account_id: int, story_id: int | None = None):
    try:
        return await client(request)
    except Exception as exc:
        logger.warning("analytics request failed account=%s story=%s method=%s error=%s", account_id, story_id, type(request).__name__, exc)
        return None


async def collect_account(account_id: int, db: Session, client) -> int:
    account = db.get(TelegramAccount, account_id)
    if account is None:
        return 0
    result = await _call(client, functions.stories.GetPeerStoriesRequest(peer=types.InputPeerSelf()), account_id)
    stories_field = getattr(result, "stories", []) if result else []
    stories = list(stories_field) if isinstance(stories_field, (list, tuple)) else list(getattr(stories_field, "stories", []) or [])
    offset_id = 0
    while True:
        page = await _call(client, functions.stories.GetStoriesArchiveRequest(peer=types.InputPeerSelf(), offset_id=offset_id, limit=100), account_id)
        page_field = getattr(page, "stories", []) if page else []
        page_stories = list(page_field) if isinstance(page_field, (list, tuple)) else list(getattr(page_field, "stories", []) or [])
        stories.extend(page_stories)
        if len(page_stories) < 100:
            break
        next_offset = min((getattr(s, "id", offset_id) for s in page_stories), default=offset_id)
        if next_offset == offset_id:
            break
        offset_id = next_offset

    seen: set[int] = set()
    for item in stories:
        telegram_id = int(getattr(item, "id", 0))
        if not telegram_id or telegram_id in seen:
            continue
        seen.add(telegram_id)
        peer_id = int(account.telegram_user_id or 0)
        story = db.query(Story).filter_by(account_id=account_id, peer_id=peer_id, telegram_story_id=telegram_id).first()
        if story is None:
            story = Story(account_id=account_id, peer_id=peer_id, telegram_story_id=telegram_id, source="analytics")
            db.add(story)
        story.source = "analytics"
        story.published_at = _dt(getattr(item, "date", None))
        story.expires_at = _dt(getattr(item, "expire_date", None))
        story.raw_data = json.dumps({"caption": getattr(item, "caption", None)}, ensure_ascii=False)
        db.flush()
        await collect_story(story, db, client)
    account.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return len(seen)


async def collect_story(story: Story, db: Session, client) -> None:
    result = await _call(client, functions.stories.GetStoriesViewsRequest(peer=types.InputPeerSelf(), id=[story.telegram_story_id]), story.account_id, story.telegram_story_id)
    items = list(getattr(result, "views", []) or []) if result else []
    aggregate = items[0] if items else result
    views_count = _attr(aggregate, "views_count", "views", default=None)
    forwards_count = _attr(aggregate, "forwards_count", "forwards", default=None)
    reactions = _attr(aggregate, "reactions", default=[]) or []
    reactions_count = _attr(aggregate, "reactions_count", default=None)
    if reactions_count is None:
        reactions_count = sum(int(getattr(r, "count", 0) or 0) for r in reactions)
    db.add(StoryStatsSnapshot(story_id=story.id, views_count=views_count, forwards_count=forwards_count, reactions_count=reactions_count))
    for reaction in reactions:
        key = _reaction_key(getattr(reaction, "reaction", reaction))
        row = db.query(StoryReactionStat).filter_by(story_id=story.id, reaction=key).first()
        if row is None:
            row = StoryReactionStat(story_id=story.id, reaction=key, count=0)
            db.add(row)
        row.count = int(getattr(reaction, "count", 0) or 0)

    offset = ""
    for _ in range(10):
        viewer_result = await _call(client, functions.stories.GetStoryViewsListRequest(peer=types.InputPeerSelf(), id=story.telegram_story_id, limit=100, offset=offset, just_contacts=False), story.account_id, story.telegram_story_id)
        if not viewer_result:
            break
        users = {int(getattr(user, "id", 0)): user for user in (getattr(viewer_result, "users", []) or [])}
        for viewer in list(getattr(viewer_result, "views", []) or []):
            user_id = int(getattr(viewer, "user_id", 0) or 0)
            if not user_id:
                continue
            row = db.query(StoryViewer).filter_by(story_id=story.id, telegram_user_id=user_id).first()
            if row is None:
                row = StoryViewer(story_id=story.id, telegram_user_id=user_id)
                db.add(row)
            row.viewed_at = _dt(getattr(viewer, "date", None))
            user = users.get(user_id)
            if user is not None:
                row.username = getattr(user, "username", None)
                row.first_name = getattr(user, "first_name", None)
                row.last_name = getattr(user, "last_name", None)
            raw_reaction = getattr(viewer, "reaction", None)
            row.reaction = _reaction_key(raw_reaction) if raw_reaction else None
        next_offset = getattr(viewer_result, "next_offset", None)
        if not next_offset or next_offset == offset:
            break
        offset = next_offset
    db.commit()
