from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel as _BM
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import WhitelistEntry
from .deps import require_api_token
from .schemas import ListOut, list_out

logger = logging.getLogger("storywatcher.api.whitelist")

router = APIRouter(prefix="/whitelist", tags=["whitelist"], dependencies=[Depends(require_api_token)])

Db = Annotated[Session, Depends(get_db)]


class ListIn(_BM):
    account_id: int
    peer_id: int | None = None
    username: str | None = None
    comment: str | None = None


@router.get("", response_model=list[ListOut])
def list_whitelist(db: Db, account_id: int | None = None):
    q = db.query(WhitelistEntry).order_by(WhitelistEntry.created_at.desc())
    if account_id is not None:
        q = q.filter(WhitelistEntry.account_id == account_id)
    return [list_out(e) for e in q.all()]


@router.post("", response_model=ListOut, status_code=201)
def add_whitelist(payload: ListIn, db: Db):
    e = WhitelistEntry(
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
def remove_whitelist(entry_id: int, db: Db):
    e = db.get(WhitelistEntry, entry_id)
    if e is None:
        raise HTTPException(status_code=404, detail="entry not found")
    db.delete(e)
    db.commit()
    return {"ok": True}