"""Regression tests for the silent-account-death fixes.

Covers the two documented incidents:

* Sep 26 — ``is_user_authorized()`` swallowed an RPC/network error, returned
  False and the worker flipped the account to DISCONNECTED + monitoring=False
  with no trace.  Now that only happens on a *confirmed* revocation, monitored
  via ``check_authorization`` and ``account_status`` activity events.
* Oct 01 — the substring check ``"authorization key" in str(exc)`` matched BOTH
  AuthKeyDuplicated AND AuthKeyUnregistered messages, wrongly deleting a valid
  session file; and the re-login created an entity-less SQLite session so the
  worker failed 22 items with ``peer not found``.

These tests are built on exception *messages* (not isinstance) so they pass
whether or not :mod:`telethon` is installed — ``classify_telegram_error`` falls
back to message matching on both.  A few tests intentionally exercise the real
Telethon API surface (``TelegramClient.is_user_authorized``, error classes) to
pin that the code never calls a method TelegramClient does not implement.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models import AccountStatus, ActivityLog, TelegramAccount
from app.services import account_state as astate
from app.services.account_state import (
    AUTH_DUPLICATED,
    AUTH_UNREGISTERED,
    DB_LOCKED,
    FLOOD_WAIT,
    NETWORK,
    TRANSIENT_RPC,
)


# --------------------------------------------------------------------------
# Error classification (message-based; no telethon required)
# --------------------------------------------------------------------------

class _FakeRPCError(Exception):
    """Raiseable stand-in for a Telethon RPC error with a free-form message."""

    message = ""
    error_message = ""

    def __init__(self, message=""):
        super().__init__(message)
        self.message = message
        self.error_message = message


def _exc(message=""):
    return _FakeRPCError(message)

def test_duplicated_authorization_key_drops_session():
    # Message fallback (works even when Telethon is not importable).
    category, drop = astate.classify_telegram_error(
        _exc("AUTH_KEY_DUPLICATED: The used authorization key is duplicated")
    )
    assert category == AUTH_DUPLICATED
    assert drop is True


def test_unregistered_authorization_key_keeps_session():
    # The old substring check matched "authorization key" here and deleted the
    # session file. The classifier must keep it (drop=False).
    category, drop = astate.classify_telegram_error(
        _exc("The authorization key is not registered")
    )
    assert category == AUTH_UNREGISTERED
    assert drop is False


def test_unregistered_key_worded_with_invalid_keeps_session():
    category, drop = astate.classify_telegram_error(_exc("AUTH_KEY_INVALID: The auth key is invalid"))
    assert category == AUTH_UNREGISTERED
    assert drop is False


def test_flood_wait_is_not_an_auth_error():
    from telethon import errors

    category, drop = astate.classify_telegram_error(errors.FloodWaitError(request=None))
    assert category == FLOOD_WAIT
    assert drop is False


def test_plain_rpc_error_is_transient():
    from telethon import errors

    category, drop = astate.classify_telegram_error(
        errors.RPCError(request=None, message="INTERNAL_SERVER_ERROR: internal error")
    )
    assert category == TRANSIENT_RPC
    assert drop is False


def test_real_telethon_auth_key_classes_classify():
    from telethon import errors

    cat, drop = astate.classify_telegram_error(errors.AuthKeyDuplicatedError(request=None))
    assert (cat, drop) == (AUTH_DUPLICATED, True)

    cat, drop = astate.classify_telegram_error(errors.AuthKeyUnregisteredError(request=None))
    assert (cat, drop) == (AUTH_UNREGISTERED, False)

    cat, drop = astate.classify_telegram_error(
        errors.UnauthorizedError(request=None, message="AUTH_KEY_UNREGISTERED: session revoked")
    )
    assert (cat, drop) == (AUTH_UNREGISTERED, False)


def test_database_locked_is_classified():
    if hasattr(__import__("sqlite3"), "OperationalError"):
        import sqlite3

        category, _ = astate.classify_telegram_error(sqlite3.OperationalError("database is locked"))
        assert category == DB_LOCKED


def test_network_error_is_classified():
    category, drop = astate.classify_telegram_error(ConnectionError("connection refused"))
    assert category == NETWORK
    assert drop is False


# --------------------------------------------------------------------------
# account_status events
# --------------------------------------------------------------------------

def _seed_account(db, user_id, status="ACTIVE", monitoring=True, session_path="/data/sessions/account_X.session", phone=None):
    import uuid

    acc = TelegramAccount(
        user_id=user_id, phone=phone or f"+19999{uuid.uuid4().hex[:8]}", status=status,
        monitoring=monitoring, session_path=session_path,
    )
    db.add(acc)
    db.commit()
    return acc


def _account_events(db, account_id):
    rows = (
        db.query(ActivityLog)
        .filter(ActivityLog.event_type == "account_status", ActivityLog.account_id == account_id)
        .all()
    )
    return [json.loads(r.meta_json or "{}") for r in rows]


def test_log_transition_persists_diagnostic_event(db, user_id):
    acc = _seed_account(db, user_id)

    astate.log_transition(
        account_id=acc.id,
        prev_status="ACTIVE",
        new_status="AUTH_REQUIRED",
        prev_monitoring=True,
        new_monitoring=True,
        source=astate.SOURCE_WORKER,
        reason="confirmed auth-key failure",
        exc=_exc("The authorization key is not registered"),
        db=db,
    )

    events = _account_events(db, acc.id)
    assert len(events) == 1
    meta = events[0]
    assert meta["previous_status"] == "ACTIVE"
    assert meta["new_status"] == "AUTH_REQUIRED"
    assert meta["previous_monitoring"] is True
    assert meta["new_monitoring"] is True
    assert meta["source"] == astate.SOURCE_WORKER
    assert meta["exception_type"] == "_FakeRPCError"
    assert "authorization key" in (meta["message"] or "")


def test_log_transition_if_changed_skips_noops(db, user_id):
    acc = _seed_account(db, user_id)

    astate.log_transition_if_changed(
        account_id=acc.id,
        prev_status="ACTIVE", new_status="ACTIVE",
        prev_monitoring=True, new_monitoring=True,
        source=astate.SOURCE_SCHEDULER,
        reason="sync sweep",
        db=db,
    )

    assert _account_events(db, acc.id) == []


# --------------------------------------------------------------------------
# Per-account transient backoff
# --------------------------------------------------------------------------

def test_transient_backoff_bounds_retries():
    astate.reset_for_tests()
    try:
        assert astate.in_transient_backoff(7) is False
        astate.mark_transient(7, backoff_s=60.0)
        assert astate.in_transient_backoff(7) is True
        astate.clear_transient(7)
        assert astate.in_transient_backoff(7) is False
    finally:
        astate.reset_for_tests()


# --------------------------------------------------------------------------
# check_authorization: confirmed loss vs transient blip
# --------------------------------------------------------------------------

def _fake_client(users_result=None, raise_exc=None):
    async def _call(request, *a, **kw):
        if raise_exc is not None:
            raise raise_exc
        return users_result

    # Deliberately exposes only the real Telethon call surface: a regression
    # that calls ``client.has_authorization()`` (which TelegramClient does not
    # implement) will raise AttributeError here.
    FakeClient = type("FakeClient", (), {"__call__": _call})
    return FakeClient()


def test_telegram_client_api_surface():
    from telethon import TelegramClient

    assert hasattr(TelegramClient, "is_user_authorized")
    assert not hasattr(TelegramClient, "has_authorization")


def test_check_authorization_authorized(db):
    astate.reset_for_tests()
    try:
        from telethon import types

        client = _fake_client(users_result=[types.User(id=1)])
        state = asyncio.run(astate.check_authorization(client, 1))

        assert state == "authorized"
    finally:
        astate.reset_for_tests()


def test_check_authorization_no_key_is_unauthorized(db):
    from telethon.errors import AuthKeyUnregisteredError

    client = _fake_client(raise_exc=AuthKeyUnregisteredError(request=None))
    state = asyncio.run(astate.check_authorization(client, 1))
    assert state == "unauthorized"


def test_check_authorization_transient_on_backoff_does_not_call_rpc(db):
    astate.reset_for_tests()
    try:
        astate.mark_transient(1, backoff_s=60.0)
        client = _fake_client(users_result=[])
        state = asyncio.run(astate.check_authorization(client, 1))
        assert state == "transient"
    finally:
        astate.reset_for_tests()


def test_check_authorization_confirmed_revocation_is_unauthorized(db):
    astate.reset_for_tests()
    try:
        client = _fake_client(raise_exc=_exc("The authorization key is not registered"))
        state = asyncio.run(astate.check_authorization(client, 1))
        assert state == "unauthorized"
    finally:
        astate.reset_for_tests()


def test_check_authorization_transient_error_sets_backoff(db):
    astate.reset_for_tests()
    try:
        client = _fake_client(raise_exc=TimeoutError("timed out"))
        state = asyncio.run(astate.check_authorization(client, 1))
        assert state == "transient"
        assert astate.in_transient_backoff(1) is True
    finally:
        astate.reset_for_tests()


def test_warm_entity_cache_uses_real_telethon_api():
    from app.telegram import client_manager as cm

    seen = []

    class _Warm:
        # Only the real TelegramClient surface: no has_authorization().
        def is_connected(self):
            return True

        async def connect(self):
            return None

        async def is_user_authorized(self):
            return True

        async def __call__(self, request):
            seen.append(request)
            return []

        session = SimpleNamespace(_entities={1: 1, 2: 2})

    asyncio.run(cm._warm_entity_cache(_Warm(), SimpleNamespace(id=7)))
    assert len(seen) == 1, "contacts request must be issued"


# --------------------------------------------------------------------------
# Worker: uniform AUTH_REQUIRED handling keeps monitoring + logs events
# --------------------------------------------------------------------------

def _import_worker():
    from app.workers import queue_worker

    return queue_worker


def test_handle_auth_key_failure_keeps_monitoring_and_keeps_file(db, user_id, tmp_path):
    qw = _import_worker()
    session = tmp_path / "account_X.session"
    session.write_bytes(b"not really a session")
    acc = _seed_account(db, user_id, session_path=str(session))

    qw._handle_auth_key_failure(
        db, acc, _exc("The authorization key is not registered"),
        requested_drop=False,
    )

    db.expire_all()
    acc = db.get(TelegramAccount, acc.id)
    assert acc.status == AccountStatus.AUTH_REQUIRED.value
    assert acc.monitoring is True, "monitoring intent must survive an auth loss"
    assert session.exists(), "unregistered key must NOT delete the session file"
    events = _account_events(db, acc.id)
    assert len(events) == 1
    assert events[0]["new_status"] == "AUTH_REQUIRED"
    assert events[0]["new_monitoring"] is True


def test_handle_auth_key_failure_drops_file_on_duplicated_key(db, user_id, tmp_path):
    qw = _import_worker()
    session = tmp_path / "account_Y.session"
    session.write_bytes(b"not really a session")
    acc = _seed_account(db, user_id, session_path=str(session))

    qw._handle_auth_key_failure(
        db, acc, _exc("AUTH_KEY_DUPLICATED: The used authorization key is duplicated"),
        requested_drop=True,
    )

    db.expire_all()
    acc = db.get(TelegramAccount, acc.id)
    assert acc.status == AccountStatus.AUTH_REQUIRED.value
    assert acc.monitoring is True
    assert not session.exists()
    assert acc.session_path is None


# --------------------------------------------------------------------------
# run_once excludes accounts that need re-login / are gone
# --------------------------------------------------------------------------

def test_run_once_skips_auth_required_and_disconnected(engine, db, user_id, tmp_path):
    from app.workers import queue_worker

    active = _seed_account(db, user_id, status="ACTIVE", monitoring=True, session_path=str(tmp_path / "a.session"))
    _seed_account(db, user_id, status="AUTH_REQUIRED", monitoring=True, session_path=str(tmp_path / "b.session"))
    _seed_account(db, user_id, status="DISCONNECTED", monitoring=True, session_path=str(tmp_path / "c.session"))

    for name in ("a.session", "b.session", "c.session"):
        (tmp_path / name).write_bytes(b"x")

    from sqlalchemy.orm import sessionmaker

    fake_sl = sessionmaker(bind=engine)
    drained = []

    async def _drain(db2, account):
        drained.append(account.id)
        return 0

    astate.reset_for_tests()
    try:
        with patch.object(queue_worker, "SessionLocal", fake_sl):
            with patch.object(queue_worker, "_drain_account", new=_drain):
                result = asyncio.run(queue_worker.run_once())
    finally:
        astate.reset_for_tests()

    assert result == 0
    assert drained == [active.id], "only the ACTIVE account may be drained"


# --------------------------------------------------------------------------
# mark_account_auth_required (client_manager) preserves monitoring
# --------------------------------------------------------------------------

def test_mark_account_auth_required_preserves_monitoring(db, engine, user_id, tmp_path):
    from app.telegram import client_manager as cm
    from sqlalchemy.orm import sessionmaker

    fake_sl = sessionmaker(bind=engine)
    session = tmp_path / "acct.session"
    session.write_bytes(b"x")
    acc = _seed_account(db, user_id, status="ACTIVE", monitoring=True, session_path=str(session))

    with patch.object(cm, "drop_client", new=AsyncMock()):
        # Point both the client_manager helper AND the activity logger at the
        # test database so the account_status event is persisted alongside the
        # account row.
        with patch("app.db.SessionLocal", fake_sl):
            with patch("app.services.activity.SessionLocal", fake_sl):
                asyncio.run(cm.mark_account_auth_required(acc.id, drop_session=True, reason="test"))

    db.expire_all()
    acc = db.get(TelegramAccount, acc.id)
    assert acc.status == AccountStatus.AUTH_REQUIRED.value
    assert acc.monitoring is True
    assert not session.exists()
    events = _account_events(db, acc.id)
    assert len(events) == 1
    assert events[0]["reason"] == "test"


# --------------------------------------------------------------------------
# processor: bounded lazy peer retry heals entity-less sessions
# --------------------------------------------------------------------------

def test_resolve_peer_heals_after_contacts_refresh():
    from app.queue.processor import _resolve_peer

    refreshed = {"done": False}

    async def refresh(client, account_id=None):
        refreshed["done"] = True

    calls = {"n": 0}

    async def get_input_entity(peer_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Could not find the input entity for PeerUser")
        return f"InputPeer({peer_id})"

    client = SimpleNamespace(get_input_entity=get_input_entity)

    with patch("app.queue.processor._refresh_contacts", new=refresh):
        result = asyncio.run(_resolve_peer(client, 99, account_id=7))

    assert result == "InputPeer(99)"
    assert refreshed["done"] is True


def test_resolve_peer_raises_when_still_unresolved():
    from app.queue.processor import _resolve_peer

    async def get_input_entity(peer_id):
        raise ValueError("Could not find the input entity for PeerUser")

    client = SimpleNamespace(get_input_entity=get_input_entity)
    with patch("app.queue.processor._refresh_contacts", new=AsyncMock()):
        with pytest.raises(ValueError):
            asyncio.run(_resolve_peer(client, 99))


def test_refresh_contacts_surfaces_auth_errors_for_classification():
    # A dead session during the retry refresh must be classified as auth so the
    # worker can demote the account (silent-failure guard).
    from app.queue.processor import _is_auth_error

    assert _is_auth_error(_exc("AUTH_KEY_DUPLICATED: The used authorization key is duplicated")) is True
    assert _is_auth_error(_exc("AUTH_KEY_UNREGISTERED: The auth key is not registered")) is True
    assert _is_auth_error(TimeoutError("timed out")) is False