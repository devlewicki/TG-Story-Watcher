from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel as _BM
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AutomationRule, TelegramAccount
from .deps import require_api_token, current_user_id
from .schemas import RuleOut, rule_out

logger = logging.getLogger("storywatcher.api.rules")

router = APIRouter(prefix="/rules", tags=["rules"], dependencies=[Depends(require_api_token)])

Db = Annotated[Session, Depends(get_db)]


class RuleIn(_BM):
    account_id: int
    name: str
    enabled: bool = True
    source_type: str = "monitor"
    config: dict = {}
    priority: int = 0


@router.get("", response_model=list[RuleOut])
def list_rules(db: Db, user_id: Annotated[int, Depends(current_user_id)], account_id: int | None = None):
    q = db.query(AutomationRule).join(TelegramAccount).filter(TelegramAccount.user_id == user_id).order_by(AutomationRule.priority.desc(), AutomationRule.id.desc())
    if account_id is not None:
        q = q.filter(AutomationRule.account_id == account_id)
    return [rule_out(r) for r in q.all()]


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(payload: RuleIn, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    if db.query(TelegramAccount).filter_by(id=payload.account_id, user_id=user_id).first() is None: raise HTTPException(404, "account not found")
    r = AutomationRule(
        account_id=payload.account_id,
        name=payload.name,
        enabled=payload.enabled,
        source_type=payload.source_type,
        config=json.dumps(payload.config, default=str),
        priority=payload.priority,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return rule_out(r)


@router.patch("/{rule_id}", response_model=RuleOut)
def patch_rule(rule_id: int, payload: RuleIn, db: Db, user_id: Annotated[int, Depends(current_user_id)]):
    r = db.query(AutomationRule).join(TelegramAccount).filter(AutomationRule.id == rule_id, TelegramAccount.user_id == user_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="rule not found")
    r.name = payload.name
    r.enabled = payload.enabled
    r.source_type = payload.source_type
    r.config = json.dumps(payload.config, default=str)
    r.priority = payload.priority
    db.commit()
    db.refresh(r)
    return rule_out(r)


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Db):
    r = db.query(AutomationRule).join(TelegramAccount).filter(AutomationRule.id == rule_id, TelegramAccount.user_id == user_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="rule not found")
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/{rule_id}/enable")
def enable_rule(rule_id: int, db: Db):
    r = db.query(AutomationRule).join(TelegramAccount).filter(AutomationRule.id == rule_id, TelegramAccount.user_id == user_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="rule not found")
    r.enabled = True
    db.commit()
    return {"ok": True, "id": rule_id, "enabled": True}


@router.post("/{rule_id}/disable")
def disable_rule(rule_id: int, db: Db):
    r = db.query(AutomationRule).join(TelegramAccount).filter(AutomationRule.id == rule_id, TelegramAccount.user_id == user_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="rule not found")
    r.enabled = False
    db.commit()
    return {"ok": True, "id": rule_id, "enabled": False}


@router.post("/{rule_id}/test")
def test_rule(rule_id: int, db: Db):
    """Lightweight validation test - verifies the rule config is well-formed JSON."""
    r = db.query(AutomationRule).join(TelegramAccount).filter(AutomationRule.id == rule_id, TelegramAccount.user_id == user_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="rule not found")
    try:
        json.loads(r.config or "{}")
        ok = True
        msg = "rule config is valid"
    except ValueError as exc:
        ok = False
        msg = f"rule config is invalid: {exc}"
    return {"ok": ok, "id": rule_id, "result": msg}