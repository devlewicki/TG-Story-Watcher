from __future__ import annotations
import json
import math
from sqlalchemy.orm import Session
from ..models import SettingsStore


def compute_all_from_daily(daily: int) -> dict:
    """Compute all system parameters from a single daily views limit.

    Returns a dict of section_name -> {key: value} with derived values for
    limits, monitoring, queue, and view sections.
    """
    daily = max(50, min(12000, daily))

    # ── Limits ──────────────────────────────────────────────────────
    views_per_hour = daily // 24
    views_per_minute = math.ceil(daily / 1440)
    searches_per_hour = max(1, min(10, daily // 1500))
    search_results_max = 50
    search_delay = max(60, min(600, 900 - (daily // 20)))

    # ── View delays ─────────────────────────────────────────────────
    # Average seconds between views for uniform distribution across 24h.
    avg_delay = 86400.0 / daily
    min_delay = max(3, min(20, round(avg_delay * 0.3)))
    max_delay = max(10, min(120, round(avg_delay * 1.5)))

    # ── Queue ───────────────────────────────────────────────────────
    if daily >= 8000:
        parallel = 3
    elif daily >= 3000:
        parallel = 2
    else:
        parallel = 1
    max_tasks = 50
    backoff_factor = 2.0
    processing_timeout = 300
    max_auto_retries = 3

    # ── Monitoring ──────────────────────────────────────────────────
    check_interval = max(15, min(60, 120 - (daily // 100)))

    return {
        "limits": {
            "views_per_day": daily,
            "views_per_hour": views_per_hour,
            "views_per_minute": views_per_minute,
            "searches_per_hour": searches_per_hour,
            "search_results_max": search_results_max,
            "search_delay": search_delay,
        },
        "view": {
            "min_delay": min_delay,
            "max_delay": max_delay,
        },
        "queue": {
            "max_tasks": max_tasks,
            "parallel": parallel,
            "backoff_factor": backoff_factor,
            "processing_timeout": processing_timeout,
            "max_auto_retries": max_auto_retries,
        },
        "monitoring": {
            "check_interval": check_interval,
        },
    }


class SettingsService:
    DEFAULTS={
        "general": {"language": "en", "timezone": "UTC", "theme": "dark", "autostart": True},
        "telegram": {"api_id": None, "api_hash": None, "reconnect": True},
        "monitoring": {"check_interval": 30, "realtime": True, "resync": True},
        "queue": {"max_tasks": 50, "parallel": 1, "backoff_factor": 2.0, "processing_timeout": 300, "max_auto_retries": 3},
        "limits": {"views_per_minute": 0, "views_per_hour": 0, "views_per_day": 800, "searches_per_hour": 5, "search_results_max": 50, "search_delay": 300},
        "view": {"min_delay": 20, "max_delay": 120, "auto_like": False, "like_emoji": "👍"},
        "discovery": {"hashtags": [], "locations": [], "enabled": False, "hashtags_enabled": True},
        "filters": {"include_contacts": False, "include_unknown": True, "include_mutual_contacts": False, "include_non_mutual": True, "include_channels": True, "include_groups": True, "include_bots": True, "include_deleted": False, "include_blocked": False},
    }

    def __init__(self, db: Session, user_id: int | None = None):
        self.db, self.user_id = db, user_id

    def _key(self, s):
        return f"user:{self.user_id}:{s}" if self.user_id is not None else s

    def _merge(self, s, v):
        out = dict(self.DEFAULTS.get(s, {}))
        out.update(v or {})
        return out

    def _rederive_from_daily(self, data: dict) -> dict:
        """Recompute all auto-derived fields from the stored views_per_day."""
        daily = int(data.get("views_per_day", 800))
        derived = compute_all_from_daily(daily)
        # Merge limits-derived fields into the limits dict
        for k, v in derived["limits"].items():
            data[k] = v
        return data

    def get(self, s):
        row = self.db.get(SettingsStore, self._key(s))
        if not row:
            return dict(self.DEFAULTS.get(s, {}))
        try:
            data = self._merge(s, json.loads(row.value or "{}"))
        except json.JSONDecodeError:
            return dict(self.DEFAULTS.get(s, {}))
        # Always re-derive limits from daily
        if s == "limits":
            data = self._rederive_from_daily(data)
        # Re-derive view delays and queue from daily
        elif s in ("view", "queue", "monitoring"):
            # Find the stored daily limit to recompute
            limits_row = self.db.get(SettingsStore, self._key("limits"))
            if limits_row:
                try:
                    ld = json.loads(limits_row.value or "{}")
                    daily = int(ld.get("views_per_day", 800))
                except (json.JSONDecodeError, ValueError):
                    daily = 800
            else:
                daily = 800
            derived = compute_all_from_daily(daily)
            if s in derived:
                for k, v in derived[s].items():
                    data[k] = v
        return data

    def get_all(self):
        return {s: self.get(s) for s in self.DEFAULTS}

    def set(self, s, v):
        key = self._key(s)
        merged = self._merge(s, v)
        row = self.db.get(SettingsStore, key)

        # When limits are saved, enforce cap and recompute all derived sections
        if s == "limits" and "views_per_day" in merged:
            daily = min(int(merged["views_per_day"]), 12000)
            daily = max(50, daily)
            derived = compute_all_from_daily(daily)
            merged.update(derived["limits"])

        if row is None:
            self.db.add(SettingsStore(key=key, value=json.dumps(merged)))
        else:
            row.value = json.dumps(merged)
        self.db.commit()
        return merged

    def set_all(self, values):
        # Extract daily limit to compute cross-section derivatives
        limits_input = values.get("limits", {})
        daily_raw = limits_input.get("views_per_day")
        if daily_raw is not None:
            daily = max(50, min(12000, int(daily_raw)))
            derived = compute_all_from_daily(daily)
            # Inject derived values into each section before saving
            for section_name, section_derived in derived.items():
                if section_name in values:
                    values[section_name].update(section_derived)
                else:
                    values[section_name] = section_derived

        for s, v in values.items():
            if s in self.DEFAULTS:
                self.set(s, v)
        return self.get_all()
