"""Tests for concurrent account draining in the queue worker.

Covers the new ``run_once`` fan-out: accounts are drained in parallel (capped
by ``ACCOUNT_DRAIN_PARALLEL``) instead of serially, while still skipping
AUTH_REQUIRED/BANNED accounts and returning the total processed count.

The test environment has no pytest async plugin, so each test drives the
coroutines through ``asyncio.run`` from a sync body.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.orm import sessionmaker

import app.workers.queue_worker as qw
from app.models import AccountStatus, TelegramAccount


@pytest.fixture()
def wsession(monkeypatch, engine):
    """Bind the worker's module-level SessionLocal to the test engine."""
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(qw, "SessionLocal", Session)
    return Session


_ID_SEQ = [1000]


def _seed_accounts(db, *, n: int, status="ACTIVE", monitoring=True):
    accs = []
    for _ in range(n):
        cid = _ID_SEQ[0]
        _ID_SEQ[0] += 1
        acc = TelegramAccount(
            id=cid,
            user_id=42,
            phone=f"+1000{cid:07d}",
            status=status,
            monitoring=monitoring,
            session_path=f"/tmp/s{cid}.session",
        )
        db.add(acc)
        accs.append(acc)
    db.commit()
    return accs


def test_run_once_no_accounts(wsession, db):
    assert asyncio.run(qw.run_once()) == 0


def test_run_once_drains_all_accounts(wsession, db, monkeypatch):
    _seed_accounts(db, n=3)

    async def fake_drain(sess, account):
        return 7

    monkeypatch.setattr(qw, "drain_queue", fake_drain)
    assert asyncio.run(qw.run_once()) == 21


def test_run_once_skips_auth_required_and_banned(wsession, db, monkeypatch):
    actives = _seed_accounts(db, n=1, status="ACTIVE")
    _seed_accounts(db, n=1, status="AUTH_REQUIRED")
    _seed_accounts(db, n=1, status="BANNED_OR_RESTRICTED")
    actives += _seed_accounts(db, n=1, status="ACTIVE")
    expected = {a.id for a in actives}

    drained = []

    async def fake_drain(sess, account):
        drained.append(account.id)
        return 1

    monkeypatch.setattr(qw, "drain_queue", fake_drain)
    assert asyncio.run(qw.run_once()) == 2
    assert set(drained) == expected


def test_run_once_drains_accounts_in_parallel(wsession, db, monkeypatch):
    monkeypatch.setattr(qw, "ACCOUNT_DRAIN_PARALLEL", 2)
    _seed_accounts(db, n=4)

    async def drive():
        active = 0
        max_active = 0
        started = 0
        wait = asyncio.Event()

        async def fake_drain(sess, account):
            nonlocal active, max_active, started
            active += 1
            max_active = max(max_active, active)
            started += 1
            await asyncio.sleep(0.05)
            await wait.wait()
            active -= 1
            return 1

        monkeypatch.setattr(qw, "drain_queue", fake_drain)

        task = asyncio.create_task(qw.run_once())
        await asyncio.sleep(0.15)

        # Both slots should be in flight before any of them completes.
        assert started == 2
        assert max_active == 2
        assert not task.done()

        wait.set()
        result = await task
        assert result == 4
        assert started == 4

    asyncio.run(drive())


def test_run_once_parallelism_capped(wsession, db, monkeypatch):
    monkeypatch.setattr(qw, "ACCOUNT_DRAIN_PARALLEL", 2)
    _seed_accounts(db, n=6)

    async def drive():
        active = 0
        max_active = 0

        async def fake_drain(sess, account):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1
            return 1

        monkeypatch.setattr(qw, "drain_queue", fake_drain)
        result = await qw.run_once()
        assert result == 6
        assert max_active <= 2

    asyncio.run(drive())


def test_drain_account_sets_error_status_on_failure(wsession, db, monkeypatch):
    acc = _seed_accounts(db, n=1)[0]

    async def drive():
        async def broken_drain(sess, account):
            raise (ConnectionError("boom"))

        async def fake_reconnect(account):
            return account

        _orig_sleep = asyncio.sleep

        async def fast_sleep(delay):
            await _orig_sleep(0)

        monkeypatch.setattr(qw, "drain_queue", broken_drain)
        monkeypatch.setattr(qw.cm, "reconnect", fake_reconnect)
        # Drain failures are retried on attempts 0-1 then escalated on 2;
        # flatten the backoff sleeps so the test stays fast.
        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        result = await qw._drain_account(db, acc)
        assert result == 0

    asyncio.run(drive())
    db.refresh(acc)
    assert acc.status == AccountStatus.ERROR.value