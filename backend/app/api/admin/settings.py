"""Admin: global system settings (runtime), with secret masking."""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...admin_auth import client_ip, current_admin, require_admin_permission
from ...admin_models import AdminUser
from ...config import get_settings
from ...db import get_db
from ...models import SettingsStore
from ...services import admin_audit
from ...services.settings_service import SettingsService

router = APIRouter(tags=["admin-settings"])
Db = Annotated[Session, Depends(get_db)]

_SECRET_HINTS = ("hash", "password", "secret", "token", "key")


def _is_secret(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in _SECRET_HINTS)


@router.get("/settings")
def get_settings_view(
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
):
    """Global (non-user) settings from settings_store + environment summary."""
    rows = db.query(SettingsStore).filter(~SettingsStore.key.like("user:%")).all()
    sections: dict[str, Any] = {}
    for row in rows:
        # Keys are section names for global settings; JSON values.
        try:
            sections[row.key] = json.loads(row.value)
        except (ValueError, TypeError):
            sections[row.key] = row.value

    # Environment-level settings (infrastructure): masked.
    env = get_settings()
    environment = {
        "database_url": {"configured": True, "masked": _mask_url(env.database_url)},
        "redis_url": {"configured": bool(env.redis_url), "masked": _mask_url(env.redis_url) if env.redis_url else None},
        "telegram_api_id": {"configured": env.telegram_api_id is not None},
        "telegram_api_hash": {"configured": bool(env.telegram_api_hash)},
        "telegram_proxy_enabled": {"value": env.telegram_proxy_enabled},
        "sessions_dir": {"value": env.sessions_dir},
        "secret_key": {"configured": bool(env.secret_key)},
    }
    return {"sections": sections, "environment": environment}


def _mask_url(url: str) -> str:
    try:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            creds, host = rest.rsplit("@", 1)
            return f"{scheme}://•••@{host}"
        return url
    except ValueError:
        return "•••"


class SettingsUpdateIn(BaseModel):
    section: str
    values: dict[str, Any]


@router.put("/settings")
def update_settings(
    payload: SettingsUpdateIn,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    """Update one global settings section (runtime settings only)."""
    if payload.section.startswith("user:"):
        raise HTTPException(400, "user settings are managed per-user")
    # Merge with existing values in the section.
    row = db.get(SettingsStore, payload.section)
    current: dict[str, Any] = {}
    if row is not None:
        try:
            current = json.loads(row.value)
        except (ValueError, TypeError):
            current = {}
    # Guard: don't allow writing secrets in plain settings.
    for key in payload.values:
        if _is_secret(key):
            raise HTTPException(400, f"setting '{key}' looks like a secret; use environment configuration")
    current.update(payload.values)
    value = json.dumps(current)
    if row is None:
        db.add(SettingsStore(key=payload.section, value=value))
    else:
        row.value = value
    db.commit()
    admin_audit.audit(
        admin_id=admin.id,
        admin_username=admin.username,
        action="settings.update",
        target=f"section:{payload.section}",
        ip=client_ip(request),
        metadata={"keys": sorted(payload.values.keys())},
    )
    return {"ok": True, "section": payload.section, "values": current}


@router.get("/settings/defaults")
def settings_defaults(
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=False))],
):
    return {"defaults": SettingsService.DEFAULTS}
