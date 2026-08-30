from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AccountStatus, TelegramAccount
from ..telegram import client_manager as cm
from .deps import require_api_token
from .schemas import AccountOut, account_out

logger = logging.getLogger("storywatcher.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

Db = Annotated[Session, Depends(get_db)]

# Note: auth endpoints are deliberately NOT protected by the API token so that
# the panel can perform the step-wise Telegram login. In practice the panel is
# already behind the token (frontend won't expose the flow without a token),
# so this is acceptable for a self-hosted single-user tool.


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


@router.post("/send-code")
async def send_code(payload: SendCodeIn):
    try:
        await cm.auth_send_code(payload.phone)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"failed to send code: {exc}")
    return {"status": "code_sent"}


@router.post("/confirm-code", response_model=AuthStatusOut)
async def confirm_code(payload: ConfirmCodeIn, db: Db):
    try:
        result = await cm.auth_confirm_code(payload.phone, payload.code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"confirmation failed: {exc}")

    if result.get("status") == "twofa":
        return AuthStatusOut(status="twofa", needs_password=True)
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("error") or result.get("status", "error"))

    # Bind the authorized session to an account record.
    acc = db.query(TelegramAccount).filter_by(phone=payload.phone).first()
    if acc is None:
        acc = TelegramAccount(phone=payload.phone, status=AccountStatus.ACTIVE.value)
        db.add(acc)
        db.commit()
        db.refresh(acc)
    try:
        client = await cm.finish_login(payload.phone, acc)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"session finalize failed: {exc}")
    if client is not None:
        await cm.update_account_identity(acc, client)
        acc.status = AccountStatus.ACTIVE.value
    db.commit()
    # Release the session so the combined worker process can own the client.
    await cm.release_client(acc.id)
    return AuthStatusOut(status="authed", needs_password=False)


@router.post("/confirm-password")
async def confirm_password(payload: ConfirmPasswordIn, db: Db):
    try:
        ok = await cm.auth_confirm_password(payload.phone, payload.password)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"password confirmation failed: {exc}")
    if not ok:
        raise HTTPException(status_code=400, detail="invalid 2FA password")

    acc = db.query(TelegramAccount).filter_by(phone=payload.phone).first()
    if acc is None:
        acc = TelegramAccount(phone=payload.phone, status=AccountStatus.ACTIVE.value)
        db.add(acc)
        db.commit()
        db.refresh(acc)
    try:
        client = await cm.finish_login(payload.phone, acc)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"session finalize failed: {exc}")
    if client is not None:
        await cm.update_account_identity(acc, client)
        acc.status = AccountStatus.ACTIVE.value
    db.commit()
    # Release the session so the combined worker process can own the client.
    await cm.release_client(acc.id)
    return {"status": "authed"}


@router.get("/status")
async def auth_status(db: Db):
    accounts = db.query(TelegramAccount).all()
    return {
        "accounts": [account_out(a) for a in accounts],
    }