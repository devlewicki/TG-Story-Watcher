"""
Migration: recalculate ALL derived settings from views_per_day.

For every user-scoped settings row, this script:
1. Reads the current views_per_day from the limits section
2. Caps it at 12000
3. Recomputes derived values for limits, view, queue, and monitoring sections
4. Saves the updated settings back

Run with:
    python3 migrate_limits_derived.py
"""
from __future__ import annotations

import json
import logging

from app.db import SessionLocal, init_db
from app.models import SettingsStore
from app.services.settings_service import compute_all_from_daily

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DAILY_CAP = 12000
DAILY_MIN = 50


def migrate() -> None:
    init_db()
    db = SessionLocal()
    updated = 0
    skipped = 0
    try:
        # Find all user-scoped limits rows
        rows = (
            db.query(SettingsStore)
            .filter(SettingsStore.key.like("user:%:limits"))
            .all()
        )
        logger.info("Found %d user limits rows to process", len(rows))

        for row in rows:
            try:
                data = json.loads(row.value or "{}")
            except json.JSONDecodeError:
                logger.warning("Skipping %s — invalid JSON", row.key)
                skipped += 1
                continue

            daily = data.get("views_per_day")
            if daily is None:
                logger.info("Skipping %s — no views_per_day", row.key)
                skipped += 1
                continue

            daily = int(daily)
            clamped = max(DAILY_MIN, min(DAILY_CAP, daily))

            # Extract user_id from key "user:{uid}:limits"
            prefix = "user:"
            suffix = ":limits"
            uid_str = row.key[len(prefix): -len(suffix)]

            # Compute all derived values
            derived = compute_all_from_daily(clamped)

            changes = []

            # Update limits section
            if clamped != daily:
                changes.append(f"views_per_day: {daily}->{clamped}")
            for k, v in derived["limits"].items():
                old = data.get(k)
                if old != v:
                    data[k] = v
                    changes.append(f"{k}: {old}->{v}")

            if changes:
                row.value = json.dumps(data)
                updated += 1
                logger.info("%s: %s", row.key, ", ".join(changes))
            else:
                skipped += 1
                logger.info("%s: limits already up-to-date", row.key)

            # Update view section
            view_key = f"user:{uid_str}:view"
            view_row = db.get(SettingsStore, view_key)
            if view_row:
                try:
                    vdata = json.loads(view_row.value or "{}")
                except json.JSONDecodeError:
                    vdata = {}
                view_changes = []
                for k, v in derived["view"].items():
                    old = vdata.get(k)
                    if old != v:
                        vdata[k] = v
                        view_changes.append(f"{k}: {old}->{v}")
                if view_changes:
                    view_row.value = json.dumps(vdata)
                    logger.info("%s: %s", view_key, ", ".join(view_changes))
                    updated += 1
                else:
                    logger.info("%s: already up-to-date", view_key)

            # Update queue section
            queue_key = f"user:{uid_str}:queue"
            queue_row = db.get(SettingsStore, queue_key)
            if queue_row:
                try:
                    qdata = json.loads(queue_row.value or "{}")
                except json.JSONDecodeError:
                    qdata = {}
                queue_changes = []
                for k, v in derived["queue"].items():
                    old = qdata.get(k)
                    if old != v:
                        qdata[k] = v
                        queue_changes.append(f"{k}: {old}->{v}")
                if queue_changes:
                    queue_row.value = json.dumps(qdata)
                    logger.info("%s: %s", queue_key, ", ".join(queue_changes))
                    updated += 1
                else:
                    logger.info("%s: already up-to-date", queue_key)

            # Update monitoring section
            mon_key = f"user:{uid_str}:monitoring"
            mon_row = db.get(SettingsStore, mon_key)
            if mon_row:
                try:
                    mdata = json.loads(mon_row.value or "{}")
                except json.JSONDecodeError:
                    mdata = {}
                mon_changes = []
                for k, v in derived["monitoring"].items():
                    old = mdata.get(k)
                    if old != v:
                        mdata[k] = v
                        mon_changes.append(f"{k}: {old}->{v}")
                if mon_changes:
                    mon_row.value = json.dumps(mdata)
                    logger.info("%s: %s", mon_key, ", ".join(mon_changes))
                    updated += 1
                else:
                    logger.info("%s: already up-to-date", mon_key)

        db.commit()
        logger.info("Migration complete: %d rows updated, %d skipped", updated, skipped)
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
