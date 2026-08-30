from __future__ import annotations

"""Shared Pydantic models / serialization helpers for the API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OkResponse(BaseModel):
    ok: bool = True


class ErrorResponse(BaseModel):
    detail: str


class AccountOut(BaseModel):
    id: int
    phone: str
    telegram_user_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    status: str
    monitoring: bool
    auto_view: bool
    last_seen_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StoryOut(BaseModel):
    id: int
    account_id: int
    peer_id: int
    telegram_story_id: int
    author_username: str | None = None
    author_name: str | None = None
    source: str
    published_at: datetime | None = None
    expires_at: datetime | None = None
    discovered_at: datetime | None = None
    liked: bool = False
    like_emoji: str | None = None
    last_viewed_at: datetime | None = None
    view_count: int = 0


class QueueItemOut(BaseModel):
    id: int
    account_id: int
    story_id: int
    status: str
    priority: int
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempts: int
    error: str | None = None
    created_at: datetime | None = None
    story: StoryOut | None = None


class ViewOut(BaseModel):
    id: int
    account_id: int
    peer_id: int
    telegram_story_id: int
    story_id: int | None = None
    source: str | None = None
    rule_id: int | None = None
    viewed_at: datetime | None = None
    status: str
    error: str | None = None


class ListOut(BaseModel):
    id: int
    account_id: int
    peer_id: int | None = None
    username: str | None = None
    comment: str | None = None
    created_at: datetime | None = None


class RuleOut(BaseModel):
    id: int
    account_id: int
    name: str
    enabled: bool
    source_type: str
    config: dict = Field(default_factory=dict)
    priority: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ActivityOut(BaseModel):
    id: int
    account_id: int | None = None
    level: str
    event_type: str
    message: str
    metadata: Any = None
    created_at: datetime | None = None


def account_out(a) -> AccountOut:
    return AccountOut(
        id=a.id,
        phone=a.phone,
        telegram_user_id=a.telegram_user_id,
        username=a.username,
        first_name=a.first_name,
        last_name=a.last_name,
        status=a.status,
        monitoring=a.monitoring,
        auto_view=a.auto_view,
        last_seen_at=a.last_seen_at,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def story_out(
    s,
    liked: bool = False,
    like_emoji: str | None = None,
    last_viewed_at: datetime | None = None,
    view_count: int = 0,
) -> StoryOut:
    return StoryOut(
        id=s.id,
        account_id=s.account_id,
        peer_id=s.peer_id,
        telegram_story_id=s.telegram_story_id,
        author_username=s.author_username,
        author_name=s.author_name,
        source=s.source,
        published_at=s.published_at,
        expires_at=s.expires_at,
        discovered_at=s.discovered_at,
        liked=liked,
        like_emoji=like_emoji,
        last_viewed_at=last_viewed_at,
        view_count=view_count,
    )


def queue_out(q) -> QueueItemOut:
    return QueueItemOut(
        id=q.id,
        account_id=q.account_id,
        story_id=q.story_id,
        status=q.status,
        priority=q.priority,
        scheduled_at=q.scheduled_at,
        started_at=q.started_at,
        completed_at=q.completed_at,
        attempts=q.attempts,
        error=q.error,
        created_at=q.created_at,
        story=story_out(q.story) if getattr(q, "story", None) is not None else None,
    )


def rule_out(r) -> RuleOut:
    import json

    try:
        cfg = json.loads(r.config or "{}")
    except (ValueError, TypeError):
        cfg = {}
    return RuleOut(
        id=r.id,
        account_id=r.account_id,
        name=r.name,
        enabled=r.enabled,
        source_type=r.source_type,
        config=cfg,
        priority=r.priority,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def activity_out(a) -> ActivityOut:
    import json

    try:
        meta = json.loads(a.meta_json) if a.meta_json else None
    except (ValueError, TypeError):
        meta = a.meta_json
    return ActivityOut(
        id=a.id,
        account_id=a.account_id,
        level=a.level,
        event_type=a.event_type,
        message=a.message,
        metadata=meta,
        created_at=a.created_at,
    )


def list_out(e) -> ListOut:
    return ListOut(
        id=e.id,
        account_id=e.account_id,
        peer_id=e.peer_id,
        username=e.username,
        comment=e.comment,
        created_at=e.created_at,
    )