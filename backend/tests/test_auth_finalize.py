"""Regression tests for the logout -> re-login flow.

After logging out, the account row is kept (phone in digit form, e.g.
``79990230230``, status DISCONNECTED, no session). When the user logs back in
typing the phone WITH a '+' prefix (``+79990230230``), the old code created a
duplicate TelegramAccount row that collided with the unique phone index and
aborted finalization with a UniqueViolation.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.auth import _account_for_phone, _finalize
from app.models import TelegramAccount


def _me(phone="79990230230", id=1399782097, username="mlewicki",
        first_name="Maxim", last_name="Lewicki"):
    return SimpleNamespace(
        phone=phone, id=id, username=username,
        first_name=first_name, last_name=last_name,
    )


def _logged_out_row(db, user_id, phone="79990230230"):
    acc = TelegramAccount(
        user_id=user_id, phone=phone, status="DISCONNECTED",
        monitoring=False, telegram_user_id=None, username=None,
        first_name=None, last_name=None, session_path=None,
    )
    db.add(acc)
    db.commit()
    return acc


def _patched_finalize(db, user_id, entered_phone, me_phone):
    me = _me(me_phone)
    login_client = SimpleNamespace(get_me=AsyncMock(return_value=me))

    async def fake_finish_login(phone, account):
        # Mirrors the real finish_login: saves the fresh session to the path.
        account.session_path = f"/data/sessions/account_{account.id}.session"
        return login_client

    with (
        patch("app.api.auth.cm.finish_login", new=fake_finish_login),
        patch("app.api.auth.cm.release_client", new=AsyncMock()),
    ):
        return asyncio.run(_finalize(entered_phone, db, user_id))


def test_reauth_with_plus_reuses_existing_row(db, user_id):
    """Full user scenario: logout row (7999...) -> login as '+7999...'."""
    row = _logged_out_row(db, user_id, phone="79990230230")

    result = _patched_finalize(db, user_id, entered_phone="+79990230230", me_phone="79990230230")

    assert result.status == "authed"
    assert result.needs_password is False
    db.expire_all()
    rows = db.query(TelegramAccount).all()
    assert len(rows) == 1, "a duplicate account row must not be created"
    acc = rows[0]
    assert acc.id == row.id
    assert acc.phone == "79990230230"
    assert acc.status == "ACTIVE"
    assert acc.telegram_user_id == 1399782097
    assert acc.session_path == f"/data/sessions/account_{row.id}.session"
    assert acc.user_id == user_id


def test_digit_phone_with_legacy_plus_row_merges(db, user_id):
    """Legacy row stored WITH '+' collides with a digit-form login."""
    row = _logged_out_row(db, user_id, phone="+79990230230")

    result = _patched_finalize(db, user_id, entered_phone="79990230230", me_phone="79990230230")

    assert result.status == "authed"
    db.expire_all()
    rows = db.query(TelegramAccount).all()
    assert len(rows) == 1, "legacy duplicates must be merged into one canonical row"
    acc = rows[0]
    assert acc.id == row.id
    assert acc.phone == "79990230230"
    assert acc.status == "ACTIVE"


def test_account_for_phone_normalizes_format(db, user_id):
    _logged_out_row(db, user_id, phone="79990230230")

    acc = _account_for_phone(db, "+79990230230", user_id)
    db.flush()

    assert acc.phone == "79990230230"
    assert db.query(TelegramAccount).count() == 1, "no duplicate must be created"