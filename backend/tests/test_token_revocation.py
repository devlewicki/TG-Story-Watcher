"""Tests for token revocation and ghost-user rejection.

Covers:
* a token issued for a user that was deleted by an admin is rejected (this
  previously produced FK-violation 500s instead of a clean 401);
* ``revoke_user_tokens`` actually invalidates tokens carrying an ``iat`` claim,
  while legacy tokens without ``iat`` keep the old (backward-compatible)
  expiry-based behaviour;
* the API answers 401 for a ghost token, letting the frontend drop the session;
* a DB error inside auth finalization surfaces as a readable 500 instead of a
  raw IntegrityError leaking into the response.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi import HTTPException

from app.api.auth import _finalize
from app.models import User
from app.multitenancy import create_user_token, revoke_user_tokens, user_id_from_token


def _make_user(db) -> int:
    user = User(
        first_name="Token",
        last_name="Ghost",
        email=f"ghost{uuid.uuid4().hex[:6]}@t.io",
        password_hash="x",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


def test_ghost_token_rejected_when_user_deleted(client, db):
    uid = _make_user(db)
    token = create_user_token(uid)
    assert user_id_from_token(token) == uid

    db.delete(db.get(User, uid))
    db.commit()

    assert user_id_from_token(token) is None
    res = client.post(
        "/api/auth/send-code",
        json={"phone": "79990001122"},
        headers={"X-API-Token": token},
    )
    assert res.status_code == 401


def test_revoke_user_tokens_invalidates_issued_tokens(client, db):
    uid = _make_user(db)
    token = create_user_token(uid)
    assert user_id_from_token(token) == uid

    revoke_user_tokens(uid)

    assert user_id_from_token(token) is None


def test_legacy_token_without_iat_survives_revoke(client, db):
    """Tokens minted before the ``iat`` claim keep the old expiry check."""
    uid = _make_user(db)
    now = int(time.time())
    payload = base64.urlsafe_b64encode(json.dumps({
        "user_id": uid, "exp": now + 86400 * 30,
    }, separators=(",", ":")).encode()).decode().rstrip("=")
    from app.config import get_settings
    legacy = f"user.{payload}.{hmac.new(get_settings().secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()}"

    revoke_user_tokens(uid)

    assert user_id_from_token(legacy) == uid


def test_finalize_db_error_is_clean_500(db, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    def boom(db_session, phone, user_id):
        raise IntegrityError("INSERT INTO telegram_accounts", {}, Exception("FK fail"))

    monkeypatch.setattr("app.api.auth._account_for_phone", boom)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(_finalize("79990001122", db, 42))
    assert ei.value.status_code == 500
    assert "session finalize failed" in str(ei.value.detail)