"""Shared fixtures for integration tests.

Uses an in-memory SQLite database so tests are fast and isolated.
Overrides the module-level engine and lifespan to avoid PostgreSQL connection.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db import Base, get_db
from app.models import (
    ActivityLog, GeoPlace, Story, StoryQueue, StoryStatsSnapshot,
    StoryView, TelegramAccount, User,
)
from app.multitenancy import create_user_token
from app.main import app


# ---------- Database fixtures ----------

@pytest.fixture()
def engine():
    import uuid
    # Use a unique shared-cache in-memory SQLite per test so each test
    # gets its own isolated database while all connections within a test
    # see the same data (plain :memory: creates a new DB per connection).
    db_name = f"test_{uuid.uuid4().hex}"
    eng = create_engine(
        f"sqlite:///file:{db_name}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    @event.listens_for(eng, "connect")
    def _pragma(dbapi_conn, _):
        dbapi_conn.cursor().execute("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def client(db):
    def _override_get_db():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = _override_get_db
    from app import db as app_db_mod
    orig_engine = app_db_mod.engine
    orig_SessionLocal = app_db_mod.SessionLocal
    # Patch both the engine and SessionLocal so any code path that creates
    # its own session (e.g. background tasks) also hits the test DB.
    app_db_mod.engine = db.get_bind()
    app_db_mod.SessionLocal = sessionmaker(bind=db.get_bind())
    with patch("app.main.init_db"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    app_db_mod.engine = orig_engine
    app_db_mod.SessionLocal = orig_SessionLocal
    app.dependency_overrides.clear()


# ---------- Token / user fixtures ----------

@pytest.fixture()
def user_id():
    return 42

@pytest.fixture()
def api_token(user_id):
    return create_user_token(user_id)

@pytest.fixture()
def auth_headers(api_token):
    return {"X-API-Token": api_token}


# ---------- Data seeding helpers ----------

@pytest.fixture()
def seed_accounts(db, user_id):
    acc1 = TelegramAccount(
        id=101, user_id=user_id, phone="+1000000001", status="ACTIVE",
        monitoring=True, auto_view=True, session_path="/tmp/s1.session",
    )
    acc2 = TelegramAccount(
        id=102, user_id=user_id, phone="+1000000002", status="ACTIVE",
        monitoring=True, auto_view=False, session_path="/tmp/s2.session",
    )
    db.add_all([acc1, acc2])
    db.commit()
    return [acc1, acc2]


@pytest.fixture()
def seed_stories(db, seed_accounts):
    now = datetime.now(timezone.utc)
    stories = []
    for i in range(30):
        acc = seed_accounts[i % 2]
        s = Story(
            id=1000 + i, account_id=acc.id, peer_id=2000 + i,
            telegram_story_id=3000 + i,
            author_username=f"user{i}", author_name=f"User {i}",
            source="monitor" if i % 3 != 0 else "analytics",
            published_at=now - timedelta(hours=i),
            discovered_at=now - timedelta(hours=i),
        )
        db.add(s)
        stories.append(s)
    db.commit()
    return stories


@pytest.fixture()
def seed_views(db, seed_accounts, seed_stories):
    """Create view records for some stories.

    story_views has UNIQUE(account_id, peer_id, telegram_story_id), so each
    view must be from a unique account for the same peer/story combo.  We use
    both accounts and create one extra view from the second account for story 0.
    """
    now = datetime.now(timezone.utc)
    views = []
    # View first 10 stories, alternating accounts
    for i in range(10):
        sv = StoryView(
            account_id=seed_accounts[i % 2].id,
            story_id=seed_stories[i].id,
            peer_id=seed_stories[i].peer_id,
            telegram_story_id=seed_stories[i].telegram_story_id,
            source="monitor",
            viewed_at=now - timedelta(hours=i),
            status="VIEWED",
        )
        db.add(sv)
        views.append(sv)
    # One extra view for story 0 from the OTHER account
    other_acc = seed_accounts[1]
    sv = StoryView(
        account_id=other_acc.id,
        story_id=seed_stories[0].id,
        peer_id=seed_stories[0].peer_id,
        telegram_story_id=seed_stories[0].telegram_story_id,
        source="monitor",
        viewed_at=now - timedelta(minutes=50),
        status="VIEWED",
    )
    db.add(sv)
    views.append(sv)
    db.commit()
    return views


@pytest.fixture()
def seed_activity(db, seed_accounts, seed_stories):
    now = datetime.now(timezone.utc)
    logs = []
    for i in range(3):
        meta = json.dumps({
            "peer_id": seed_stories[i].peer_id,
            "story_id": seed_stories[i].telegram_story_id,
            "emoji": "❤️",
        })
        al = ActivityLog(
            account_id=seed_accounts[i % 2].id,
            event_type="story_liked", level="INFO",
            message=f"Story liked: peer={seed_stories[i].peer_id}",
            meta_json=meta, created_at=now - timedelta(minutes=i),
        )
        db.add(al)
        logs.append(al)
    for i in range(5):
        meta = json.dumps({"peer_id": 9999, "story_id": 9999, "reason": "filtered"})
        al = ActivityLog(
            account_id=seed_accounts[0].id,
            event_type="story_skipped", level="INFO",
            message="Story skipped", meta_json=meta,
            created_at=now - timedelta(hours=i),
        )
        db.add(al)
        logs.append(al)
    for i in range(2):
        al = ActivityLog(
            account_id=seed_accounts[0].id,
            event_type="worker_error", level="ERROR",
            message="worker failed",
            created_at=now - timedelta(minutes=30),
        )
        db.add(al)
        logs.append(al)
    db.commit()
    return logs


@pytest.fixture()
def seed_queue(db, seed_accounts, seed_stories):
    now = datetime.now(timezone.utc)
    items = []
    for i, status in enumerate(["PENDING", "WAITING_DELAY", "PROCESSING", "VIEWED", "FAILED", "EXPIRED"]):
        item = StoryQueue(
            account_id=seed_accounts[i % 2].id,
            story_id=seed_stories[i].id,
            status=status, priority=i,
            scheduled_at=now - timedelta(minutes=i),
        )
        db.add(item)
        items.append(item)
    db.commit()
    return items
