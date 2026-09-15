"""Regression tests for the Telegram login code flow and user deletion.

Covers:
* SEND_CODE_UNAVAILABLE (Telegram exhausted the number's delivery options) is
  surfaced as a friendly 429 instead of the raw RPC error;
* a send-code cooldown prevents hammering the number with resends;
* re-login for a phone wiped by ``clear_login_state`` starts from a clean slate
  (no stale client with a cached phone_code_hash -> no auth.resendCode);
* admin ``DELETE /api/admin/users/{id}`` releases the Telegram resources
  (cached client, session files, login state) so a fresh login with the same
  phone no longer fails with "failed to send code".
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.admin_models import AdminRole, AdminUser
from app.api.auth import _friendly_auth_error
from app.models import SettingsStore, TelegramAccount, User
from app.multitenancy import hash_password
from app.telegram import client_manager as cm


def _make_send_unavailable():
    from telethon import errors as tl_errors

    return tl_errors.SendCodeUnavailableError(request=SimpleNamespace())


def test_friendly_auth_error_maps_send_unavailable():
    msg = _friendly_auth_error(_make_send_unavailable())
    assert msg is not None
    assert "ограничил" in msg


def test_friendly_auth_error_none_for_unknown():
    assert _friendly_auth_error(ValueError("boom")) is None


def test_send_code_returns_429_on_cooldown(client, auth_headers):
    with patch(
        "app.api.auth.cm.auth_send_code",
        new=AsyncMock(side_effect=cm.CooldownError("79990001122", 30.0)),
    ):
        res = client.post("/api/auth/send-code", json={"phone": "79990001122"}, headers=auth_headers)
    assert res.status_code == 429
    assert "Код уже отправлен" in res.json()["detail"]


def test_send_code_returns_friendly_message_on_send_unavailable(client, auth_headers):
    with patch(
        "app.api.auth.cm.auth_send_code",
        new=AsyncMock(side_effect=_make_send_unavailable()),
    ):
        res = client.post("/api/auth/send-code", json={"phone": "79990001122"}, headers=auth_headers)
    assert res.status_code == 429
    assert "ограничил" in res.json()["detail"]


def test_ensure_login_enforces_cooldown():
    phone = "79990001122"
    cm._login_clients.clear()
    cm._login_sent_at[phone] = time.monotonic() - 1.0  # sent 1s ago (< 60s cooldown)
    try:
        with pytest.raises(cm.CooldownError):
            asyncio.run(cm._ensure_login(phone))
    finally:
        cm._login_clients.clear()
        cm._login_states.clear()
        cm._login_started.clear()
        cm._login_sent_at.clear()
        cm._login_locks.clear()


def test_clear_login_state_clears_by_canonical_phone():
    phone = "+79990001122"
    login = SimpleNamespace(disconnect=AsyncMock())
    cm._login_clients[phone] = login
    cm._login_states[phone] = cm.LoginState()
    cm._login_sent_at[phone] = 10.0
    cm._login_locks[phone] = None
    try:
        cleared = asyncio.run(cm.clear_login_state("79990001122"))
        assert cleared == [phone]
        assert phone not in cm._login_clients
        assert phone not in cm._login_states
        assert phone not in cm._login_sent_at
        assert phone not in cm._login_locks
        login.disconnect.assert_awaited_once()
    finally:
        cm._login_clients.clear()
        cm._login_states.clear()
        cm._login_started.clear()
        cm._login_sent_at.clear()
        cm._login_locks.clear()


def _admin_login(client, username, password):
    return client.post("/api/admin/auth/login", json={"username": username, "password": password})


def test_delete_user_releases_telegram_resources(client, engine, tmp_path):
    from sqlalchemy.orm import sessionmaker

    TestSession = sessionmaker(bind=engine)

    db = TestSession()
    try:
        admin = AdminUser(
            username="rootdel",
            password_hash=hash_password("supersecret1"),
            role=AdminRole.SUPER_ADMIN.value,
        )
        user = User(
            first_name="Del",
            last_name="Me",
            email=f"del{uuid.uuid4().hex[:6]}@t.io",
            password_hash="x",
        )
        db.add_all([admin, user])
        db.commit()
        db.refresh(admin)
        db.refresh(user)
        session_file = tmp_path / "account_1001.session"
        session_file.write_bytes(b"SQLite format 3")
        db.add(
            TelegramAccount(
                id=1001,
                user_id=user.id,
                phone="79990001122",
                status="ACTIVE",
                monitoring=True,
                session_path=str(session_file),
            )
        )
        db.add(SettingsStore(key=f"user:{user.id}:discovery", value='{"enabled": true}'))
        db.commit()
        admin_id = admin.id
        user_id = user.id
    finally:
        db.close()

    token = _admin_login(client, "rootdel", "supersecret1").json()["token"]
    headers = {"X-Admin-Token": token}

    with (
        patch("app.api.admin.users.cm.drop_client", new=AsyncMock()) as drop_client,
        patch("app.api.admin.users.cm.clear_login_state", new=AsyncMock()) as clear_login,
    ):
        res = client.delete(f"/api/admin/users/{user_id}", headers=headers)

    assert res.status_code == 200
    assert drop_client.await_count == 1
    clear_login.assert_awaited_with("79990001122")
    assert not os.path.exists(str(session_file)), "orphaned session file must be removed"

    db = TestSession()
    try:
        # The telegram_accounts row itself is removed by the FK ON DELETE CASCADE
        # defined in the schema (enforced in production PostgreSQL); the test DB
        # runs SQLite without FK pragmas, so here we assert on the resource
        # cleanup that delete_user owns in code.
        assert db.get(User, user_id) is None
        assert db.query(SettingsStore).filter_by(key=f"user:{user_id}:discovery").first() is None
        revoked = db.query(SettingsStore).filter_by(key=f"user:{user_id}:token_revoked_at").first()
        assert revoked is not None, "revocation marker must be kept so leaked tokens stay dead"
        assert db.query(AdminUser).filter(AdminUser.id == admin_id).first() is not None
    finally:
        db.close()


def test_reconcile_orphaned_clients_drops_missing_accounts(client, db, tmp_path, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.workers import scheduler

    monkeypatch.setattr(cm.settings, "sessions_dir", str(tmp_path))
    # scheduler binds SessionLocal at import time, so patch it directly instead
    # of relying on app.db.SessionLocal (which the client fixture swaps).
    monkeypatch.setattr(scheduler, "SessionLocal", sessionmaker(bind=db.get_bind()))

    class FakeClient:
        def __init__(self, account_id):
            self.account_id = account_id

    user = User(first_name="Keep", last_name="Acc", email="keep@t.io", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    acc = TelegramAccount(
        id=2001, user_id=user.id, phone="79990001122", status="ACTIVE", monitoring=True,
        session_path=None,
    )
    db.add(acc)
    db.commit()
    keep_id = acc.id

    cm._clients[keep_id] = FakeClient(keep_id)
    cm._clients[99999] = FakeClient(99999)
    try:
        dropped = asyncio.run(scheduler.reconcile_orphaned_clients())
        assert 99999 not in cm._clients
        assert dropped == 1
        assert keep_id in cm._clients
    finally:
        cm._clients.clear()