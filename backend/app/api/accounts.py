from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AccountStatus, TelegramAccount
from ..telegram import client_manager as cm
from .deps import require_api_token, current_user_id
from .schemas import AccountOut, account_out

logger = logging.getLogger("storywatcher.api.accounts")

router = APIRouter(tags=["accounts"], dependencies=[Depends(require_api_token)])

Db = Annotated[Session, Depends(get_db)]


class AccountCreate(BaseModel):
    phone: str = Field(..., min_length=5)
    api_id: int | None = None
    api_hash: str | None = None


class AccountResponse(BaseModel):
    account_id: int
    status: str


class MonitoringUpdate(BaseModel):
    monitoring: bool


async def _load(db: Db, account_id: int) -> TelegramAccount:
    acc = db.get(TelegramAccount, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    return acc


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    return [account_out(a) for a in db.query(TelegramAccount).filter(TelegramAccount.user_id == user_id).order_by(TelegramAccount.id).all()]


@router.post("/accounts", response_model=AccountResponse, status_code=201)
def create_account(payload: AccountCreate, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    existing = db.query(TelegramAccount).filter_by(phone=payload.phone).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="account with this phone already exists")
    acc = TelegramAccount(
        phone=payload.phone,
        user_id=user_id,
        status=AccountStatus.DISCONNECTED.value,
        api_id=payload.api_id,
        api_hash=payload.api_hash,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return AccountResponse(account_id=acc.id, status=acc.status)


@router.post("/accounts/{account_id}/start")
async def start_account(account_id: int, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    """Start monitoring for the account.

    The backend must never open the Telethon session file: the combined worker
    process is its sole owner (SQLite sessions can't be shared across
    processes), and connecting here would raise ``database is locked``. So this
    only flips the monitoring flag — the worker connects and refreshes the
    authorization status on its next cycle.
    """
    acc = await _load(db, account_id)
    if acc.user_id != user_id: raise HTTPException(404, "account not found")
    acc.monitoring = True
    if acc.status in (
        AccountStatus.PAUSED.value,
        AccountStatus.ERROR.value,
        AccountStatus.DISCONNECTED.value,
    ):
        acc.status = AccountStatus.ACTIVE.value
    db.commit()
    return {"id": acc.id, "status": acc.status, "monitoring": acc.monitoring, "authorized": None}


@router.post("/accounts/{account_id}/pause")
async def pause_account(account_id: int, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    acc = await _load(db, account_id)
    if acc.user_id != user_id: raise HTTPException(404, "account not found")
    acc.status = AccountStatus.PAUSED.value
    acc.monitoring = False
    db.commit()
    return {"id": acc.id, "status": acc.status}


@router.post("/accounts/{account_id}/monitoring")
async def set_monitoring(account_id: int, payload: MonitoringUpdate, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    acc = await _load(db, account_id)
    if acc.user_id != user_id: raise HTTPException(404, "account not found")
    acc.monitoring = payload.monitoring
    db.commit()
    return {"id": acc.id, "monitoring": acc.monitoring}


@router.delete("/accounts/{account_id}", response_model=dict)
async def delete_account(account_id: int, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    acc = await _load(db, account_id)
    if acc.user_id != user_id: raise HTTPException(404, "account not found")
    await cm.drop_client(account_id)
    session_file = acc.session_path
    # Keep the TelegramAccount row as the owner of historical analytics.
    # Removing it would cascade-delete Stories, snapshots, viewers and
    # reactions. Only revoke the Telegram authorization and detach the profile.
    acc.session_path = None
    acc.status = AccountStatus.DISCONNECTED.value
    acc.monitoring = False
    acc.telegram_user_id = None
    acc.username = None
    acc.first_name = None
    acc.last_name = None
    db.commit()
    if session_file:
        import os

        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(session_file + suffix)
            except FileNotFoundError:
                pass
    return {"ok": True}