from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models import SettingsStore


class SettingsService:
    """Typed JSON settings stored in the settings_store table."""

    DEFAULTS: dict = {
        "general": {
            "language": "en",
            "timezone": "UTC",
            "theme": "dark",
            "autostart": True,
        },
        "telegram": {
            "api_id": None,
            "api_hash": None,
            "reconnect": True,
        },
        "monitoring": {
            "check_interval": 30,
            "realtime": True,
            "resync": True,
        },
        "queue": {
            "max_tasks": 1000,
            "parallel": 1,
            "backoff_factor": 2.0,
            "processing_timeout": 300,
            "max_auto_retries": 3,
        },
        "limits": {
            "views_per_minute": 10,
            "views_per_hour": 200,
            "views_per_day": 1500,
            "searches_per_hour": 10,
            "search_results_max": 50,
            "search_delay": 300,
        },
        "view": {
            "min_delay": 20,
            "max_delay": 120,
            "auto_like": False,
            "like_emoji": "👍",
        },
        "discovery": {
            "hashtags": [],
            "locations": [],
            "enabled": False,
        },
        "filters": {
            "include_contacts": False,
            "include_unknown": True,
            "include_mutual_contacts": False,
            "include_non_mutual": True,
            "include_channels": True,
            "include_groups": True,
            "include_bots": True,
            "include_deleted": False,
            "include_blocked": False,
        },
    }

    def __init__(self, db: Session):
        self.db = db

    def _merge(self, section: str, value: dict) -> dict:
        defaults = dict(self.DEFAULTS.get(section, {}))
        if isinstance(value, dict):
            defaults.update(value)
        return defaults

    def get(self, section: str) -> dict:
        row = self.db.get(SettingsStore, section)
        if not row:
            return dict(self.DEFAULTS.get(section, {}))
        try:
            return self._merge(section, json.loads(row.value or "{}"))
        except json.JSONDecodeError:
            return dict(self.DEFAULTS.get(section, {}))

    def get_all(self) -> dict:
        return {section: self.get(section) for section in self.DEFAULTS}

    def set(self, section: str, value: dict) -> dict:
        merged = self._merge(section, value)
        row = self.db.get(SettingsStore, section)
        if row is None:
            row = SettingsStore(key=section, value=json.dumps(merged))
            self.db.add(row)
        else:
            row.value = json.dumps(merged)
        self.db.commit()
        return merged

    def set_all(self, values: dict) -> dict:
        for section, value in values.items():
            if section in self.DEFAULTS:
                self.set(section, value)
        return self.get_all()


def get_settings_service(db: Session) -> SettingsService:
    return SettingsService(db)