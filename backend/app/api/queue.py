from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as _BM
from sqlalchemy import orm
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import StoryQueue, TelegramAccount
from .deps import require_api_token, current_user_id
from .schemas import QueueItemOut, queue_out

logger = logging.getLogger("storywatcher.api.queue")

router = APIRouter(prefix="/queue", tags=["queue"], dependencies=[Depends(require_api_token)])

Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[QueueItemOut])
def list_queue(
    db: Db,
    user_id: Annotated[int, Depends(current_user_id)],
    account_id: int | None = None,
    status: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    q = db.query(StoryQueue).join(TelegramAccount, StoryQueue.account_id == TelegramAccount.id).filter(TelegramAccount.user_id == user_id).options(
        orm.joinedload(StoryQueue.story)
    ).order_by(StoryQueue.scheduled_at.desc())
    if account_id is not None:
        q = q.filter(StoryQueue.account_id == account_id)
    if status is not None:
        q = q.filter(StoryQueue.status == status)
    return [queue_out(i) for i in q.offset(offset).limit(limit).all()]


@router.get("/count")
def count_queue(
    db: Db,
    user_id: Annotated[int, Depends(current_user_id)],
    account_id: int | None = None,
    status: str | None = None,
):
    q = db.query(StoryQueue).join(TelegramAccount).filter(TelegramAccount.user_id == user_id)
    if account_id is not None:
        q = q.filter(StoryQueue.account_id == account_id)
    if status is not None:
        q = q.filter(StoryQueue.status == status)
    return {"count": q.count()}


@router.post("/{item_id}/cancel")
def cancel_item(item_id: int, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    item = db.query(StoryQueue).join(TelegramAccount).filter(StoryQueue.id == item_id, TelegramAccount.user_id == user_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="queue item not found")
    if item.status not in ("VIEWED", "FAILED", "EXPIRED"):
        item.status = "CANCELLED"
        item.completed_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True, "id": item_id, "status": item.status}


@router.post("/{item_id}/retry")
def retry_item(item_id: int, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    item = db.query(StoryQueue).join(TelegramAccount).filter(StoryQueue.id == item_id, TelegramAccount.user_id == user_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="queue item not found")
    if item.status in ("VIEWED", "CANCELLED"):
        raise HTTPException(status_code=400, detail="item cannot be retried")
    import random
    from datetime import timedelta

    from ..services.settings_service import SettingsService

    svc = SettingsService(db)
    min_d = int(svc.get("view").get("min_delay", 0))
    max_d = max(int(svc.get("view").get("max_delay", 10)), min_d)
    item.status = "PENDING"
    item.error = None
    item.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=random.randint(min_d, max_d))
    item.started_at = None
    item.completed_at = None
    db.commit()
    return {"ok": True, "id": item_id, "status": item.status}


class QueuePatch(_BM):
    status: str | None = None
    scheduled_at: datetime | None = None
    priority: int | None = None


@router.patch("/{item_id}", response_model=QueueItemOut)
def patch_item(item_id: int, payload: QueuePatch, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    item = db.query(StoryQueue).join(TelegramAccount).filter(StoryQueue.id == item_id, TelegramAccount.user_id == user_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="queue item not found")
    if payload.status is not None:
        item.status = payload.status
    if payload.scheduled_at is not None:
        item.scheduled_at = payload.scheduled_at
    if payload.priority is not None:
        item.priority = payload.priority
    db.commit()
    db.refresh(item)
    return queue_out(item)


@router.delete("/clear")
def clear_queue(db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    q = db.query(StoryQueue).join(TelegramAccount).filter(TelegramAccount.user_id == user_id)
    for item in q.all():
        if item.status not in ("VIEWED", "FAILED", "EXPIRED"):
            item.status = "CANCELLED"
            item.completed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}