"""Regression: admin users list must report the REAL account status.

Track 2 — the old code derived a user-level ``blocked`` badge from a heuristic
("has accounts but none are monitoring"), which mislabeled accounts whose
session was invalidated on Telegram's side (``AUTH_REQUIRED``) as "blocked".
That is wrong: a logged-out account has monitoring off but the user is NOT
blocked.

This test locks the real behaviour: a user whose only account has
``AUTH_REQUIRED`` (monitoring off) must:
  * NOT be reported as ``blocked``;
  * expose ``account_status == "AUTH_REQUIRED"`` so the admin UI can show the
    real per-account badge instead of the FAILED/ACTIVE heuristic.
"""
from __future__ import annotations

from tests.test_admin_auth import admin_db, client, readonly_admin, super_admin  # noqa: F401

import pytest


@pytest.fixture()
def logged_out_user(engine, admin_db):
    """User with a single Telegram account whose session was revoked (AUTH_REQUIRED)."""
    from sqlalchemy.orm import sessionmaker

    from app.models import (
        AccountStatus,
        TelegramAccount,
        User,
    )
    from app.security import hash_password

    session = sessionmaker(bind=engine)()
    try:
        u = User(
            first_name="kakashka",
            last_name="regression",
            email="kakashka@mail.sru",
            password_hash=hash_password("pw12345x"),
        )
        session.add(u)
        session.flush()
        session.add(
            TelegramAccount(
                user_id=u.id,
                phone="+79990000001",
                status=AccountStatus.AUTH_REQUIRED.value,
                monitoring=False,
                session_path=None,
            )
        )
        session.commit()
        yield u
    finally:
        session.close()


def test_auth_required_account_is_not_blocked(client, admin_db, logged_out_user):
    from app.admin_auth import create_admin_session
    from app.admin_models import AdminUser

    admin = admin_db.query(AdminUser).filter(AdminUser.username == "root").one()
    token, _ = create_admin_session(admin_db, admin, ip="127.0.0.1")
    headers = {"X-Admin-Token": token}

    res = client.get("/api/admin/users", headers=headers)
    assert res.status_code == 200, res.text

    row = next(u for u in res.json()["items"] if u["id"] == logged_out_user.id)
    assert row["blocked"] is False
    assert row["account_status"] == "AUTH_REQUIRED"
    assert row["accounts"] == 1
