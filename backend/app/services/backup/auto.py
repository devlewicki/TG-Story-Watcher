"""Automatic backups: daily job driven by ``backup:auto`` settings.

Runs inside the combined worker once per hour (cheap check); creates a backup
when the scheduled hour matches and none was created today, then applies the
retention policy.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("storywatcher.backup.auto")

_last_auto_date: str | None = None


def _load_settings(db) -> dict:
    from ...models import SettingsStore

    try:
        row = db.get(SettingsStore, "backup:auto")
        if row is None:
            return {}
        return json.loads(row.value) or {}
    except Exception:  # noqa: BLE001
        return {}


def run_auto_backup_check() -> None:
    """Called periodically from the worker. Creates the daily backup when due."""
    global _last_auto_date

    from ...db import SessionLocal

    db = SessionLocal()
    try:
        cfg = _load_settings(db)
        if not cfg.get("enabled"):
            return
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        if _last_auto_date == today:
            return
        if now.hour < int(cfg.get("schedule_hour_utc", 4)):
            return

        _last_auto_date = today
        retention = int(cfg.get("retention", 7))
        encrypted = bool(cfg.get("encrypted"))
        logger.info("auto backup due (retention=%s, encrypted=%s)", retention, encrypted)
    finally:
        db.close()

    # Heavy work outside the DB session; run inline in a worker thread.
    import threading

    def _run() -> None:
        try:
            from .service import BackupService

            op_id = uuid.uuid4().hex
            svc = BackupService()
            # Automatic backups are unencrypted unless the operator provides a
            # password via BACKUP_AUTO_PASSWORD (never stored in the DB).
            import os

            pw = os.environ.get("BACKUP_AUTO_PASSWORD") if encrypted else None
            svc.create_backup(op_id=op_id, password=pw, created_by="auto")
            # Apply retention after the backup thread completes.
            import time

            for _ in range(3600):
                from ...db import SessionLocal as _SL
                from ..admin_models import BackupOperation

                _db = _SL()
                try:
                    op = _db.get(BackupOperation, op_id)
                    done = op is not None and op.status in ("SUCCESS", "FAILED")
                finally:
                    _db.close()
                if done:
                    break
                time.sleep(2)
            svc.apply_retention(keep=retention)
            logger.info("auto backup finished: op=%s", op_id)
        except Exception:  # noqa: BLE001
            logger.exception("auto backup failed")

    threading.Thread(target=_run, daemon=True, name="auto-backup").start()
