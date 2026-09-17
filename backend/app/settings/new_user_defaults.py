"""Defaults for brand-new users.

New users are seeded once at registration: base hashtags are added to their
discovery config together with a ``seed_created`` marker.  When the user later
authorizes a Telegram account, the marker tells us this is a fresh user, so we
can safely enable hashtag search and auto-start monitoring without ever
touching the settings of pre-existing users.

Base hashtags are editable in the "Story Search" page afterwards.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..services.settings_service import SettingsService

# Base hashtags stored (without the leading '#') for every new user.
BASE_HASHTAGS = [
    "спорт",
    "здоровье",
    "жизнь",
    "санктпетербург",
    "москва",
    "путешествия",
    "мотивация",
]

_SEED_MARKER = "seed_created"


def seed_new_user(db: Session, user_id: int) -> None:
    """Write base hashtags + seed marker for a freshly registered user."""
    svc = SettingsService(db, user_id)
    cfg = svc.get("discovery") or {}
    cfg["hashtags"] = _dedupe(BASE_HASHTAGS, cfg.get("hashtags"))
    cfg["hashtags_enabled"] = True
    cfg[_SEED_MARKER] = True
    svc.set("discovery", cfg)


def apply_wiring_if_new_user(
    db: Session, user_id: int, account=None
) -> bool:
    """Enable auto-search and auto-start monitoring for a fresh user.

    Only acts when the registration seed marker is present.  After the first
    successful run the marker is removed, so a later re-login never overrides
    the user's own choices.  Returns True when the wiring was applied.
    """
    svc = SettingsService(db, user_id)
    cfg = svc.get("discovery") or {}
    if not cfg.get(_SEED_MARKER):
        return False

    # Hashtags were already seeded at registration; make sure they are intact.
    cfg["hashtags"] = _dedupe(BASE_HASHTAGS, cfg.get("hashtags"))
    cfg["hashtags_enabled"] = True
    # Search by hashtags comes right after the hashtags are in place.
    cfg["enabled"] = True
    cfg.pop(_SEED_MARKER, None)
    svc.set("discovery", cfg)

    if account is not None and not account.monitoring:
        account.monitoring = True
        db.commit()

    return True


def _dedupe(base: list[str], existing) -> list[str]:
    items = list(base)
    if existing:
        items.extend(existing)
    return list(dict.fromkeys(item.strip() for item in items if item))