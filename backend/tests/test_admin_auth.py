"""Tests for admin authentication, RBAC and audit logging."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.admin_models import AdminRole, AdminUser
from app.multitenancy import hash_password


@pytest.fixture()
def admin_db(engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine)()


@pytest.fixture()
def super_admin(admin_db):
    admin = AdminUser(
        username="root",
        password_hash=hash_password("supersecret1"),
        role=AdminRole.SUPER_ADMIN.value,
    )
    admin_db.add(admin)
    admin_db.commit()
    admin_db.refresh(admin)
    return admin


@pytest.fixture()
def readonly_admin(admin_db):
    admin = AdminUser(
        username="viewer",
        password_hash=hash_password("readonlypass1"),
        role=AdminRole.READ_ONLY.value,
    )
    admin_db.add(admin)
    admin_db.commit()
    return admin


@pytest.fixture()
def client(engine, admin_db, super_admin, monkeypatch, tmp_path):
    """TestClient with get_db overridden to the test database."""
    from sqlalchemy import event
    from sqlalchemy.orm import sessionmaker

    from app.db import Base, get_db
    from app.main import app

    TestSession = sessionmaker(bind=engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    # Ensure bootstrap admin doesn't try to create another one.
    monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "x-not-used")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, username, password):
    return client.post("/api/admin/auth/login", json={"username": username, "password": password})


def test_admin_login_success(client, super_admin):
    res = _login(client, "root", "supersecret1")
    assert res.status_code == 200
    data = res.json()
    assert data["token"].startswith("adm.")
    assert data["admin"]["username"] == "root"
    assert data["admin"]["role"] == "SUPER_ADMIN"


def test_admin_login_wrong_password(client, super_admin):
    res = _login(client, "root", "wrongpassword")
    assert res.status_code == 401


def test_admin_me_requires_token(client):
    res = client.get("/api/admin/auth/me")
    assert res.status_code == 401


def test_admin_me_with_token(client, super_admin):
    token = _login(client, "root", "supersecret1").json()["token"]
    res = client.get("/api/admin/auth/me", headers={"X-Admin-Token": token})
    assert res.status_code == 200
    assert res.json()["username"] == "root"


def test_user_token_rejected_on_admin_api(client, db, monkeypatch):
    """Regular user tokens must not grant access to admin endpoints."""
    from app.models import User
    from app.multitenancy import create_user_token

    user = User(first_name="U", last_name="S", email=f"u{uuid.uuid4().hex[:6]}@t.io", password_hash="x")
    db.add(user)
    db.commit()
    user_token = create_user_token(user.id)
    res = client.get("/api/admin/auth/me", headers={"X-API-Token": user_token})
    assert res.status_code == 401


def test_readonly_cannot_write(client, readonly_admin):
    token = _login(client, "viewer", "readonlypass1").json()["token"]
    headers = {"X-Admin-Token": token}
    assert client.get("/api/admin/users", headers=headers).status_code == 200
    res = client.post("/api/admin/worker/pause", headers=headers)
    assert res.status_code == 403


def test_admin_cannot_restore_only_super(client, admin_db):
    from app.admin_models import AdminRole, AdminUser as AU

    admin = AU(username="mid", password_hash=hash_password("midpassword1"), role=AdminRole.ADMIN.value)
    admin_db.add(admin)
    admin_db.commit()
    token = _login(client, "mid", "midpassword1").json()["token"]
    res = client.post(
        "/api/admin/backups/00000000/restore",
        json={"confirm": "RESTORE"},
        headers={"X-Admin-Token": token},
    )
    assert res.status_code == 403


def test_audit_log_written_on_login(client, super_admin, engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.admin_models import AdminAuditLog
    from app.services import admin_audit

    # The audit service uses its own SessionLocal; point it at the test engine.
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr(admin_audit, "SessionLocal", TestSession)

    _login(client, "root", "supersecret1")
    db = TestSession()
    try:
        rows = db.query(AdminAuditLog).filter_by(action="admin.login").all()
    finally:
        db.close()
    assert rows, "login must be audited"
