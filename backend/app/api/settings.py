from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel as _BM
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.settings_service import SettingsService
from .deps import require_api_token

logger = logging.getLogger("storywatcher.api.settings")

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_api_token)])

Db = Annotated[Session, Depends(get_db)]


class SettingsUpdate(_BM):
    section: str
    value: dict


@router.get("")
def get_settings(db: Db):
    svc = SettingsService(db)
    return svc.get_all()


@router.post("")
def update_settings(payload: SettingsUpdate, db: Db):
    svc = SettingsService(db)
    if payload.section not in svc.DEFAULTS:
        return {"ok": False, "error": f"unknown section: {payload.section}"}
    merged = svc.set(payload.section, payload.value)
    return {"ok": True, "section": payload.section, "value": merged}


@router.put("")
def put_settings(values: dict, db: Db):
    svc = SettingsService(db)
    result = svc.set_all(values)
    return {"ok": True, "settings": result}