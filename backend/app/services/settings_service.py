from __future__ import annotations
import json
import math
from functools import lru_cache
from sqlalchemy.orm import Session
from ..models import SettingsStore


@lru_cache(maxsize=64)
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
    search_results_max = 20 if daily <= 200 else 50 if daily <= 2000 else 100 if daily <= 5000 else 200
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
    max_tasks = 50 if daily <= 2000 else 100 if daily <= 5000 else 200
    backoff_factor = 1.5 if daily >= 8000 else 2.0
    processing_timeout = 300 if daily <= 2000 else 600
    max_auto_retries = 3 if daily <= 5000 else 5

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
        "general": {"language": "en", "timezone": "Europe/Moscow", "theme": "dark", "autostart": True},
        "telegram": {"api_id": None, "api_hash": None, "reconnect": True},
        "monitoring": {"check_interval": 30, "realtime": True, "resync": True},
        "queue": {"max_tasks": 50, "parallel": 1, "backoff_factor": 2.0, "processing_timeout": 300, "max_auto_retries": 3},
        "limits": {"views_per_minute": 0, "views_per_hour": 0, "views_per_day": 800, "searches_per_hour": 5, "search_results_max": 50, "search_delay": 300},
        "view": {"min_delay": 20, "max_delay": 120, "auto_like": False, "like_emoji": "👍", "max_stories_per_user_per_day": 3},
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
        # Resolve stored values for every section in one query, then derive
        # the requested one.  Avoids the extra per-call limits lookup that
        # previously made get("view"/"queue"/"monitoring") do 2-3 reads.
        return self._derive(s, self._load_all())

    def _load_all(self) -> dict[str, dict]:
        rows = self.db.query(SettingsStore).filter(
            SettingsStore.key.in_([self._key(s) for s in self.DEFAULTS])
        ).all()
        raw = {s: {} for s in self.DEFAULTS}
        for r in rows:
            s = self._section_from_key(r.key)
            if s is None:
                continue
            try:
                raw[s] = json.loads(r.value or "{}")
            except json.JSONDecodeError:
                raw[s] = {}
        return raw

    def _section_from_key(self, key: str) -> str | None:
        if self.user_id is not None and key.startswith(f"user:{self.user_id}:"):
            key = key[len(f"user:{self.user_id}:"):]
        return key if key in self.DEFAULTS else None

    def _derive(self, s: str, all_raw: dict[str, dict]) -> dict:
        stored = all_raw.get(s, {})
        data = self._merge(s, stored)
        # Always re-derive limits from daily
        if s == "limits":
            data = self._rederive_from_daily(data)
        # Re-derive view delays and queue from daily
        elif s in ("view", "queue", "monitoring"):
            ld = all_raw.get("limits", {})
            try:
                daily = int(ld.get("views_per_day", 800))
            except (ValueError, TypeError):
                daily = 800
            derived = compute_all_from_daily(daily)
            if s in derived:
                for k, v in derived[s].items():
                    # Preserve explicit user overrides: never clobber a key the
                    # user stored with an auto-derived value (e.g. custom
                    # min_delay/max_delay in the view section).
                    if k in stored:
                        continue
                    # Keep non-derived view settings as-is too.
                    if s == "view" and k in ("auto_like", "like_emoji", "max_stories_per_user_per_day"):
                        continue
                    data[k] = v
        return data

    def get_all(self):
        all_raw = self._load_all()
        return {s: self._derive(s, all_raw) for s in self.DEFAULTS}

    def set(self, s, v):
        key = self._key(s)
        merged = self._merge(s, v)
        row = self.db.get(SettingsStore, key)

        # When limits are saved, enforce cap and recompute all derived sections
        if s == "limits" and "views_per_day" in merged:
            try:
                daily = int(merged["views_per_day"])
            except (ValueError, TypeError):
                daily = 800
            daily = max(50, min(12000, daily))
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
            try:
                daily = int(daily_raw)
            except (ValueError, TypeError):
                daily = 800
            daily = max(50, min(12000, daily))
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
