"""Tests for ``VpnMonitor`` hysteresis.

Egress-IP pooling providers rotate the visible IP on every new TCP
connection, so the monitor must not treat a single fresh probe as an IP
change: a re-confirmation on the next probe is required before clients are
disconnected.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.vpn_monitor import VpnMonitor


@pytest.fixture()
def monitor():
    return VpnMonitor(proxy_host="vpn", proxy_port=1080, check_interval=0.0)


def test_initial_probe_records_ip_without_callback(monitor, monkeypatch):
    monkeypatch.setattr(monitor, "check_ip", AsyncMock(return_value="1.2.3.4"))
    cb = AsyncMock()
    assert asyncio.run(monitor.tick(cb)) is False
    assert monitor._last_ip == "1.2.3.4"
    cb.assert_not_awaited()


def test_same_ip_never_triggers(monitor, monkeypatch):
    monkeypatch.setattr(monitor, "check_ip", AsyncMock(side_effect=["1.2.3.4", "1.2.3.4", "1.2.3.4"]))
    cb = AsyncMock()
    asyncio.run(monitor.tick(cb))
    assert asyncio.run(monitor.tick(cb)) is False
    assert asyncio.run(monitor.tick(cb)) is False
    cb.assert_not_awaited()


def test_single_transient_ip_change_is_ignored(monitor, monkeypatch):
    # A one-off different IP (e.g. the pool handed out another exit) is
    # treated as a candidate but not acted on.
    monkeypatch.setattr(monitor, "check_ip", AsyncMock(side_effect=["1.2.3.4", "5.6.7.8", "1.2.3.4"]))
    cb = AsyncMock()
    asyncio.run(monitor.tick(cb))
    assert asyncio.run(monitor.tick(cb)) is False
    assert monitor._last_ip == "1.2.3.4"
    assert asyncio.run(monitor.tick(cb)) is False
    assert monitor._last_ip == "1.2.3.4"
    cb.assert_not_awaited()


def test_confirmed_ip_change_triggers_once(monitor, monkeypatch):
    # Two consecutive probes reporting the same new IP confirm a real switch.
    monkeypatch.setattr(monitor, "check_ip", AsyncMock(side_effect=["1.2.3.4", "5.6.7.8", "5.6.7.8", "5.6.7.8"]))
    cb = AsyncMock()
    asyncio.run(monitor.tick(cb))
    assert asyncio.run(monitor.tick(cb)) is False  # first sighting
    assert asyncio.run(monitor.tick(cb)) is True   # confirmed
    cb.assert_awaited_once()
    assert monitor._last_ip == "5.6.7.8"
    # Subsequent probes report the new baseline — no repeat callback.
    assert asyncio.run(monitor.tick(cb)) is False
    cb.assert_awaited_once()


def test_failed_probe_is_not_a_change(monitor, monkeypatch):
    monkeypatch.setattr(monitor, "check_ip", AsyncMock(side_effect=["1.2.3.4", None]))
    cb = AsyncMock()
    asyncio.run(monitor.tick(cb))
    assert asyncio.run(monitor.tick(cb)) is False
    cb.assert_not_awaited()


def test_stability_threshold_respected(monitor, monkeypatch):
    monitor._stability_checks = 3
    monkeypatch.setattr(monitor, "check_ip", AsyncMock(side_effect=["1.2.3.4", "5.6.7.8", "5.6.7.8", "5.6.7.8", "5.6.7.8"]))
    cb = AsyncMock()
    asyncio.run(monitor.tick(cb))
    assert asyncio.run(monitor.tick(cb)) is False  # 1/3
    assert asyncio.run(monitor.tick(cb)) is False  # 2/3
    assert asyncio.run(monitor.tick(cb)) is True   # 3/3
    cb.assert_awaited_once()