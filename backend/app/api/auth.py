from __future__ import annotations

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AccountStatus, TelegramAccount
from ..telegram import client_manager as cm
from .deps import current_user_id
from .schemas import AccountOut, account_out

logger = logging.getLogger("storywatcher.api.auth")
router = APIRouter(prefix="/auth", tags=["auth"])
Db = Annotated[Session, Depends(get_db)]


class SendCodeIn(BaseModel):
    phone: str = Field(..., min_length=5)


class ConfirmCodeIn(BaseModel):
    phone: str
    code: str


class ConfirmPasswordIn(BaseModel):
    phone: str
    password: str


class AuthStatusOut(BaseModel):
    status: str
    needs_password: bool = False


def _account_for_phone(db: Session, phone: str, user_id: int) -> TelegramAccount:
    account = db.query(TelegramAccount).filter(TelegramAccount.phone == phone).first()
    if account is not None:
        if account.user_id not in (None, user_id):
            raise HTTPException(status_code=403, detail="этот Telegram-аккаунт уже подключён к другому пользователю")
        account.user_id = user_id
        return account
    account = TelegramAccount(phone=phone, user_id=user_id, status=AccountStatus.ACTIVE.value)
    db.add(account)
    db.flush()
    return account


async def _finalize(phone: str, db: Session, user_id: int) -> AuthStatusOut:
    account = _account_for_phone(db, phone, user_id)
    original_id = account.id
    try:
        client = await cm.finish_login(phone, account)
        me = await client.get_me()
        normalized_phone = getattr(me, "phone", None) if me else None
        duplicate = None
        if normalized_phone and normalized_phone != account.phone:
            duplicate = (
                db.query(TelegramAccount)
                .filter(
                    TelegramAccount.phone == normalized_phone,
                    TelegramAccount.id != account.id,
                )
                .first()
            )
        if duplicate is not None:
            if duplicate.user_id not in (None, user_id):
                raise HTTPException(status_code=403, detail="этот Telegram-аккаунт уже подключён к другому пользователю")
            old_session = account.session_path
            db.delete(account)
            db.flush()
            account = duplicate
            account.user_id = user_id
            if old_session and old_session != account.session_path:
                account.session_path = old_session
        else:
            account.phone = normalized_phone or phone
        account.telegram_user_id = getattr(me, "id", None) if me else None
        account.username = getattr(me, "username", None) if me else None
        account.first_name = getattr(me, "first_name", None) if me else None
        account.last_name = getattr(me, "last_name", None) if me else None
        account.status = AccountStatus.ACTIVE.value
        db.commit()
        if duplicate is not None and original_id != account.id:
            try:
                os.remove(_session_path_for_deleted(original_id))
            except FileNotFoundError:
                pass
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Telegram session finalization failed")
        raise HTTPException(status_code=500, detail=f"session finalize failed: {exc}")
    finally:
        await cm.release_client(original_id)
    return AuthStatusOut(status="authed", needs_password=False)


def _session_path_for_deleted(account_id: int) -> str:
    return os.path.join(cm.settings.sessions_dir, f"account_{account_id}.session")


@router.post("/send-code")
async def send_code(payload: SendCodeIn):
    try:
        await cm.auth_send_code(payload.phone)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to send code: {exc}")
    return {"status": "code_sent"}


@router.post("/confirm-code", response_model=AuthStatusOut)
async def confirm_code(payload: ConfirmCodeIn, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    try:
        result = await cm.auth_confirm_code(payload.phone, payload.code)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"confirmation failed: {exc}")
    if result.get("status") == "twofa":
        return AuthStatusOut(status="twofa", needs_password=True)
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("status", "error"))
    return await _finalize(payload.phone, db, user_id)


@router.post("/confirm-password", response_model=AuthStatusOut)
async def confirm_password(payload: ConfirmPasswordIn, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    try:
        ok = await cm.auth_confirm_password(payload.phone, payload.password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"password confirmation failed: {exc}")
    if not ok:
        raise HTTPException(status_code=400, detail="invalid 2FA password")
    return await _finalize(payload.phone, db, user_id)


@router.get("/status")
async def auth_status(db: Db):
    accounts = db.query(TelegramAccount).all()
    return {"accounts": [account_out(a) for a in accounts]}
