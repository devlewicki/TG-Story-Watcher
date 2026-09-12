"""Admin: infrastructure services health."""
from __future__ import annotations

import os
import socket
import time
import urllib.request
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...admin_auth import current_admin
from ...admin_models import AdminUser
from ...config import get_settings
from ...db import get_db
from ...workers import worker_control

router = APIRouter(tags=["admin-services"])
Db = Annotated[Session, Depends(get_db)]

_STARTED_AT = time.time()


def _tcp_ok(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:  # noqa: BLE001
        return False


@router.get("/services")
def services_status(
    db: Db,
    _admin: Annotated[AdminUser, Depends(current_admin)],
):
    now = datetime.now(timezone.utc)
    settings = get_settings()

    db_ok = True
    db_version = None
    try:
        row = db.execute(text("SELECT version()")).scalar()
        db_version = str(row).split()[1] if row else None
    except Exception:  # noqa: BLE001
        db_ok = False

    redis_ok = False
    redis_version = None
    try:
        import redis as redis_lib

        client = redis_lib.Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        redis_ok = bool(client.ping())
        info = client.info("server")
        redis_version = info.get("redis_version")
    except Exception:  # noqa: BLE001
        redis_ok = False

    worker_running = worker_control.worker_running()
    hb_age = worker_control.heartbeat_age_seconds()
    paused = worker_control.is_paused()

    # Frontend/nginx: probe only if configured (compose-internal hostnames).
    fe_host = os.environ.get("FRONTEND_HOST", "frontend")
    fe_ok = _tcp_ok(fe_host, 3000) if os.environ.get("PROBE_INTERNAL_SERVICES", "0") == "1" else None
    nginx_host = os.environ.get("NGINX_HOST", "nginx")
    nginx_ok = _tcp_ok(nginx_host, 80) if os.environ.get("PROBE_INTERNAL_SERVICES", "0") == "1" else None

    proxy_ok = None
    if settings.telegram_proxy_enabled:
        proxy_ok = _tcp_ok(settings.telegram_proxy_host, settings.telegram_proxy_port or 1080)

    services = [
        {
            "name": "backend",
            "ok": True,
            "uptime_seconds": time.time() - _STARTED_AT,
            "version": "0.1.0",
            "last_check": now.isoformat(),
        },
        {
            "name": "worker",
            "ok": worker_running,
            "paused": paused,
            "heartbeat_age": hb_age,
            "last_check": now.isoformat(),
        },
        {
            "name": "postgres",
            "ok": db_ok,
            "version": db_version,
            "last_check": now.isoformat(),
        },
        {
            "name": "redis",
            "ok": redis_ok,
            "version": redis_version,
            "last_check": now.isoformat(),
        },
        {
            "name": "frontend",
            "ok": fe_ok,
            "last_check": now.isoformat(),
        },
        {
            "name": "nginx",
            "ok": nginx_ok,
            "last_check": now.isoformat(),
        },
        {
            "name": "vpn_proxy",
            "ok": proxy_ok,
            "last_check": now.isoformat(),
        },
    ]
    return {"services": services, "checked_at": now.isoformat()}
