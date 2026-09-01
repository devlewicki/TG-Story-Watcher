from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel as _BM
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BlacklistEntry, TelegramAccount
from .deps import require_api_token, current_user_id
from .schemas import ListOut, list_out

logger = logging.getLogger("storywatcher.api.blacklist")

router = APIRouter(prefix="/blacklist", tags=["blacklist"], dependencies=[Depends(require_api_token)])

Db = Annotated[Session, Depends(get_db)]


class ListIn(_BM):
    account_id: int
    peer_id: int | None = None
    username: str | None = None
    comment: str | None = None


@router.get("", response_model=list[ListOut])
def list_blacklist(db: Db, user_id: Annotated[int, Depends(current_user_id)], account_id: int | None = None):
    q = db.query(BlacklistEntry).join(TelegramAccount).filter(TelegramAccount.user_id == user_id).order_by(BlacklistEntry.created_at.desc())
    if account_id is not None:
        q = q.filter(BlacklistEntry.account_id == account_id)
    return [list_out(e) for e in q.all()]


@router.post("", response_model=ListOut, status_code=201)
def add_blacklist(payload: ListIn, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    if db.query(TelegramAccount).filter_by(id=payload.account_id, user_id=user_id).first() is None: raise HTTPException(404, "account not found")
    e = BlacklistEntry(
        account_id=payload.account_id,
        peer_id=payload.peer_id,
        username=payload.username,
        comment=payload.comment,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return list_out(e)


@router.delete("/{entry_id}")
def remove_blacklist(entry_id: int, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    e = db.query(BlacklistEntry).join(TelegramAccount).filter(BlacklistEntry.id == entry_id, TelegramAccount.user_id == user_id).first()
    if e is None:
        raise HTTPException(status_code=404, detail="entry not found")
    db.delete(e)
    db.commit()
    return {"ok": True}