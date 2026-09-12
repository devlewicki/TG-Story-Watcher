"""Worker control: pause/resume/status/safe-restart requests.

Communication path (single worker process owns all Telethon clients):

* The admin API writes a control flag into Redis (fallback: settings_store).
* The combined worker reads the flag each cycle and acts on it.
* Status is derived from the heartbeat file + counters the worker publishes.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger("storywatcher.worker_control")

CONTROL_KEY = "worker:control"
STATUS_KEY = "worker:status"

_CONTROL_TTL = 120  # seconds; flags expire so a lost worker cannot stay paused forever


def _redis():
    try:
        import redis

        from ..config import get_settings

        url = get_settings().redis_url
        if not url:
            return None
        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def _store_get(key: str) -> str | None:
    client = _redis()
    if client is not None:
        try:
            val = client.get(key)
            return val.decode() if val else None
        except Exception:  # noqa: BLE001
            pass
    # DB fallback via settings_store
    try:
        from sqlalchemy import text

        from ..db import SessionLocal

        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT value FROM settings_store WHERE key = :k"), {"k": key}
            ).first()
            return row[0] if row else None
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return None


def _store_set(key: str, value: str) -> None:
    client = _redis()
    if client is not None:
        try:
            client.set(key, value, ex=_CONTROL_TTL if key == CONTROL_KEY else None)
        except Exception:  # noqa: BLE001
            pass
    try:
        from sqlalchemy import text

        from ..db import SessionLocal

        db = SessionLocal()
        try:
            db.execute(
                text(
                    "INSERT INTO settings_store (key, value, updated_at) "
                    "VALUES (:k, :v, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP"
                ),
                {"k": key, "v": value},
            )
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------- control API


def set_paused(paused: bool) -> None:
    _store_set(CONTROL_KEY, json.dumps({"paused": paused, "ts": time.time()}))


def is_paused() -> bool:
    raw = _store_get(CONTROL_KEY)
    if not raw:
        return False
    try:
        data = json.loads(raw)
        return bool(data.get("paused"))
    except Exception:  # noqa: BLE001
        return False


def request_restart() -> None:
    _store_set(CONTROL_KEY, json.dumps({"restart": True, "ts": time.time()}))


def consume_control() -> dict:
    """Worker-side: read and consume pending control flags (restart only)."""
    raw = _store_get(CONTROL_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    if data.get("restart"):
        _store_set(CONTROL_KEY, json.dumps({"paused": data.get("paused", False), "ts": time.time()}))
        return {"restart": True, "paused": bool(data.get("paused"))}
    return {"paused": bool(data.get("paused"))}


def publish_status(stats: dict) -> None:
    """Worker-side: publish current counters for the admin API."""
    payload = dict(stats)
    payload["ts"] = time.time()
    client = _redis()
    if client is not None:
        try:
            client.set(STATUS_KEY, json.dumps(payload))
            return
        except Exception:  # noqa: BLE001
            pass
    _store_set(STATUS_KEY, json.dumps(payload))


def read_status(max_age_seconds: float = 30.0) -> dict | None:
    raw = _store_get(STATUS_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    if time.time() - float(data.get("ts", 0)) > max_age_seconds:
        return None
    return data


HEARTBEAT_KEY = "worker:heartbeat"


def _publish_heartbeat(ts: float) -> None:
    """Worker-side: mirror the heartbeat file into Redis (and settings_store as
    a fallback) so OTHER containers (backend/admin) can read it — /tmp is not
    shared between containers."""
    client = _redis()
    if client is not None:
        try:
            client.set(HEARTBEAT_KEY, str(ts))
        except Exception:  # noqa: BLE001
            pass
    _store_set(HEARTBEAT_KEY, str(ts))


def heartbeat_age_seconds() -> float | None:
    """Age of the worker heartbeat.

    Reads the Redis-published timestamp first (works across containers);
    falls back to the local heartbeat file (same-container use).
    """
    client = _redis()
    if client is not None:
        try:
            val = client.get(HEARTBEAT_KEY)
            if val:
                return max(0.0, time.time() - float(val))
        except Exception:  # noqa: BLE001
            pass
    try:
        raw = _store_get(HEARTBEAT_KEY)
        if raw:
            return max(0.0, time.time() - float(raw))
    except Exception:  # noqa: BLE001
        pass
    # Same-container fallback: the heartbeat file.
    path = os.environ.get("WORKER_HEARTBEAT", "/tmp/worker_heartbeat")
    try:
        with open(path) as fh:
            ts = float(fh.read().strip())
        return max(0.0, time.time() - ts)
    except Exception:  # noqa: BLE001
        return None


def worker_running(max_age_seconds: float = 90.0) -> bool:
    age = heartbeat_age_seconds()
    return age is not None and age <= max_age_seconds
