"""New-user onboarding: seed at registration + wiring at Telegram connect."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.auth import _finalize
from app.models import TelegramAccount
from app.services.settings_service import SettingsService
from app.settings.new_user_defaults import (
    BASE_HASHTAGS,
    apply_wiring_if_new_user,
    seed_new_user,
)


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
        account.session_path = f"/data/sessions/account_{account.id}.session"
        return login_client

    with (
        patch("app.api.auth.cm.finish_login", new=fake_finish_login),
        patch("app.api.auth.cm.release_client", new=AsyncMock()),
    ):
        return asyncio.run(_finalize(entered_phone, db, user_id))


class TestRegistrationSeed:
    def test_register_seeds_discovery(self, db, client):
        res = client.post("/api/user-auth/register", json={
            "first_name": "New", "last_name": "User",
            "email": "newuser@example.com", "password": "password123",
        })
        assert res.status_code == 200
        uid = res.json()["user"]["id"]
        cfg = SettingsService(db, uid).get("discovery")
        assert cfg["hashtags"] == BASE_HASHTAGS
        assert cfg["hashtags_enabled"] is True
        assert cfg.get("seed_created") is True
        # Search stays off until Telegram is authorized.
        assert cfg["enabled"] is False

    def test_register_duplicate_email_not_seeded_again(self, db, client):
        payload = {
            "first_name": "A", "last_name": "B",
            "email": "dup@example.com", "password": "password123",
        }
        assert client.post("/api/user-auth/register", json=payload).status_code == 200
        res = client.post("/api/user-auth/register", json=payload)
        assert res.status_code == 409


class TestApplyWiring:
    def test_apply_for_new_user(self, db, user_id):
        seed_new_user(db, user_id)
        acc = _logged_out_row(db, user_id)

        assert apply_wiring_if_new_user(db, user_id, acc) is True

        db.expire_all()
        row = db.query(TelegramAccount).filter_by(id=acc.id).first()
        assert row.monitoring is True
        cfg = SettingsService(db, user_id).get("discovery")
        assert cfg["enabled"] is True
        assert cfg["hashtags_enabled"] is True
        assert cfg["hashtags"] == BASE_HASHTAGS
        assert "seed_created" not in cfg

        # Idempotent: after the marker is consumed, nothing else happens.
        assert apply_wiring_if_new_user(db, user_id, row) is False

    def test_preserves_user_added_hashtags(self, db, user_id):
        seed_new_user(db, user_id)
        svc = SettingsService(db, user_id)
        svc.set("discovery", {**svc.get("discovery"), "hashtags": ["хобби"]})
        acc = _logged_out_row(db, user_id)

        apply_wiring_if_new_user(db, user_id, acc)

        cfg = SettingsService(db, user_id).get("discovery")
        assert cfg["hashtags"] == [*BASE_HASHTAGS, "хобби"]

    def test_existing_user_not_touched(self, db, user_id):
        # No seed marker: a pre-existing user with their own discovery settings.
        SettingsService(db, user_id).set("discovery", {"hashtags": ["хобби"], "enabled": False})
        acc = _logged_out_row(db, user_id)

        assert apply_wiring_if_new_user(db, user_id, acc) is False

        db.expire_all()
        row = db.query(TelegramAccount).filter_by(id=acc.id).first()
        assert row.monitoring is False
        cfg = SettingsService(db, user_id).get("discovery")
        assert cfg["enabled"] is False
        assert cfg["hashtags"] == ["хобби"]
        assert "seed_created" not in cfg


class TestFinalizeFlow:
    def test_first_connect_auto_starts_and_enables_search(self, db, user_id):
        seed_new_user(db, user_id)
        _logged_out_row(db, user_id)

        result = _patched_finalize(db, user_id, "+79990230230", "79990230230")

        assert result.status == "authed"
        db.expire_all()
        row = db.query(TelegramAccount).one()
        assert row.status == "ACTIVE"
        assert row.monitoring is True
        cfg = SettingsService(db, user_id).get("discovery")
        assert cfg["enabled"] is True
        assert cfg["hashtags"] == BASE_HASHTAGS
        assert "seed_created" not in cfg

    def test_connect_without_seed_keeps_monitoring_off(self, db, user_id):
        # Existing user: no marker, and they left monitoring off.
        _logged_out_row(db, user_id)

        result = _patched_finalize(db, user_id, "+79990230230", "79990230230")

        assert result.status == "authed"
        db.expire_all()
        row = db.query(TelegramAccount).one()
        assert row.monitoring is False