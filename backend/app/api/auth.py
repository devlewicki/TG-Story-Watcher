from __future__ import annotations

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AccountStatus, TelegramAccount
from ..settings.new_user_defaults import apply_wiring_if_new_user
from ..telegram import client_manager as cm
from .deps import current_user_id
from .schemas import AccountOut, account_out

logger = logging.getLogger("storywatcher.api.auth")
router = APIRouter(prefix="/auth", tags=["auth"])
Db = Annotated[Session, Depends(get_db)]


def _friendly_auth_error(exc: Exception) -> str | None:
    """Map Telegram/Telethon errors into a user-friendly Russian message."""
    try:
        from telethon import errors as tl_errors
    except ImportError:
        return None
    if isinstance(exc, tl_errors.FloodWaitError):
        secs = getattr(exc, "seconds", None)
        if secs:
            return f"Слишком много попыток — Telegram просит подождать {int(secs)} сек."
        return "Слишком много попыток, попробуйте позже."
    if isinstance(exc, (tl_errors.SendCodeUnavailableError, tl_errors.PhoneNumberFloodError)):
        return "Telegram временно ограничил отправку кодов на этот номер — попробуйте через несколько минут."
    return None


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
    normalized = cm.normalize_phone(phone)
    # Fast path: exact match on what the user typed.
    account = db.query(TelegramAccount).filter(TelegramAccount.phone == phone).first()
    if account is None and normalized:
        # Canonical match: the same number may already be stored in digit form
        # (Telethon's User.phone). Without this, re-login after logout with a
        # differently-formatted phone created a duplicate row and the unique
        # phone index made the update collide.
        account = (
            db.query(TelegramAccount)
            .filter(TelegramAccount.phone == normalized)
            .first()
        )
    if account is None and normalized:
        # Belt-and-braces: legacy rows may carry the '+' prefix (or other
        # formatting). The table is tiny, so scanning for the canonical digits
        # is cheap and prevents yet another duplicate row for the same number.
        account = next(
            (
                a for a in db.query(TelegramAccount).all()
                if cm.normalize_phone(a.phone) == normalized
            ),
            None,
        )
    if account is not None:
        if account.user_id not in (None, user_id):
            raise HTTPException(status_code=403, detail="этот Telegram-аккаунт уже подключён к другому пользователю")
        account.user_id = user_id
        return account
    account = TelegramAccount(phone=normalized or phone, user_id=user_id, status=AccountStatus.ACTIVE.value)
    db.add(account)
    db.flush()
    return account


def _find_duplicate(db: Session, account: TelegramAccount, normalized_phone: str) -> TelegramAccount | None:
    """Another row owning the same canonical phone (any stored format)."""
    exact = (
        db.query(TelegramAccount)
        .filter(
            TelegramAccount.phone == normalized_phone,
            TelegramAccount.id != account.id,
        )
        .first()
    )
    if exact is not None:
        return exact
    for candidate in db.query(TelegramAccount).filter(TelegramAccount.id != account.id).all():
        if cm.normalize_phone(candidate.phone) == normalized_phone:
            return candidate
    return None


async def _finalize(phone: str, db: Session, user_id: int) -> AuthStatusOut:
    original_id = None
    try:
        account = _account_for_phone(db, phone, user_id)
        original_id = account.id
        client = await cm.finish_login(phone, account)
        me = await client.get_me()
        normalized_phone = cm.normalize_phone(getattr(me, "phone", None)) if me else ""
        duplicate = None
        if normalized_phone and normalized_phone != account.phone:
            duplicate = _find_duplicate(db, account, normalized_phone)
        adopted_session = False
        if duplicate is not None:
            if duplicate.user_id not in (None, user_id):
                raise HTTPException(status_code=403, detail="этот Telegram-аккаунт уже подключён к другому пользователю")
            old_session = account.session_path
            db.delete(account)
            db.flush()
            account = duplicate
            account.user_id = user_id
            account.phone = normalized_phone
            if old_session and old_session != account.session_path:
                account.session_path = old_session
                adopted_session = True
            else:
                adopted_session = False
        elif normalized_phone:
            account.phone = normalized_phone
        account.telegram_user_id = getattr(me, "id", None) if me else None
        account.username = getattr(me, "username", None) if me else None
        account.first_name = getattr(me, "first_name", None) if me else None
        account.last_name = getattr(me, "last_name", None) if me else None
        account.status = AccountStatus.ACTIVE.value
        db.commit()
        # Fresh users (seeded at registration) get hashtag search enabled and
        # monitoring auto-started right after their first Telegram authorization.
        apply_wiring_if_new_user(db, user_id, account)
        # Remove the temp row's orphan session file only when the fresh login's
        # session was NOT adopted by the surviving row (otherwise we'd delete
        # the very session the merged account now uses).
        if duplicate is not None and original_id != account.id and not adopted_session:
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
        if original_id is not None:
            await cm.release_client(original_id)
    return AuthStatusOut(status="authed", needs_password=False)


def _session_path_for_deleted(account_id: int) -> str:
    return os.path.join(cm.settings.sessions_dir, f"account_{account_id}.session")


@router.post("/send-code")
async def send_code(payload: SendCodeIn, user_id: Annotated[int, Depends(current_user_id)]):
    try:
        await cm.auth_send_code(payload.phone)
    except cm.CooldownError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except Exception as exc:
        friendly = _friendly_auth_error(exc)
        if friendly:
            raise HTTPException(status_code=429, detail=friendly)
        raise HTTPException(status_code=400, detail=f"failed to send code: {exc}")
    return {"status": "code_sent"}


@router.post("/confirm-code", response_model=AuthStatusOut)
async def confirm_code(payload: ConfirmCodeIn, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    try:
        result = await cm.auth_confirm_code(payload.phone, payload.code)
    except Exception as exc:
        friendly = _friendly_auth_error(exc)
        detail = friendly or f"confirmation failed: {exc}"
        raise HTTPException(status_code=429 if friendly else 400, detail=detail)
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
        friendly = _friendly_auth_error(exc)
        detail = friendly or f"password confirmation failed: {exc}"
        raise HTTPException(status_code=429 if friendly else 400, detail=detail)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid 2FA password")
    return await _finalize(payload.phone, db, user_id)


@router.get("/status")
async def auth_status(db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    accounts = db.query(TelegramAccount).filter(TelegramAccount.user_id == user_id).all()
    return {"accounts": [account_out(a) for a in accounts]}
