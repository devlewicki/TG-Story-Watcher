"""BackupService: portable instance snapshots.

A backup is a tar.gz archive containing the PostgreSQL dump (or the SQLite
file in dev mode), every Telethon session file, application metadata, a
manifest and per-file SHA-256 checksums. Archives may be encrypted with
AES-256-GCM from a password that is never persisted.

Structure inside the archive (see job/admin-job.md #23):

    backup/
    ├── manifest.json
    ├── database/postgres.dump
    ├── telegram/sessions/*.session
    ├── config/app-config.json
    └── metadata/{version.json, checksums.sha256}
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
from datetime import datetime, timezone

from ...admin_models import BackupOperation, BackupRecord
from ...config import get_settings
from ...db import SessionLocal, engine
from . import crypto
from .storage import default_storage

logger = logging.getLogger("storywatcher.backup")

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
CHECKSUMS_NAME = "checksums.sha256"
DB_DUMP_NAME = "database/postgres.dump"
SESSIONS_PREFIX = "telegram/sessions/"
CONFIG_NAME = "config/app-config.json"
VERSION_NAME = "metadata/version.json"
ARCHIVE_MEMBER_ROOT = "backup/"

# Only one heavy backup/restore operation at a time (guard against concurrent
# pg_restore vs pg_dump races and accidental parallel restores).
_op_lock = threading.Lock()


def _db() -> SessionLocal:  # noqa: N802 - small helper for readability
    return SessionLocal()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BackupError(Exception):
    pass


class BackupService:
    def __init__(self, storage=None):
        self.storage = storage or default_storage()

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _set_progress(op_id: str, progress: int, stage: str | None = None) -> None:
        db = _db()
        try:
            op = db.get(BackupOperation, op_id)
            if op is not None:
                op.progress = max(op.progress, min(100, max(0, progress)))
                if stage is not None:
                    op.stage = stage
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def _finish_op(op_id: str, status: str, error: str | None = None) -> None:
        db = _db()
        try:
            op = db.get(BackupOperation, op_id)
            if op is not None:
                op.status = status
                op.progress = 100 if status == "SUCCESS" else op.progress
                op.finished_at = datetime.now(timezone.utc)
                op.error = error[:2000] if error else None
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def _start_op(op_id: str) -> None:
        db = _db()
        try:
            op = db.get(BackupOperation, op_id)
            if op is not None:
                op.status = "RUNNING"
                op.started_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()

    # --------------------------------------------------------------- database
    def _dump_postgres(self, workdir: str) -> str:
        """Create a consistent PostgreSQL dump via pg_dump (custom format)."""
        url = engine.url
        dump_path = os.path.join(workdir, "postgres.dump")
        env = dict(os.environ)
        # Build connection args from the SQLAlchemy URL.
        cmd = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file", dump_path,
        ]
        conn = []
        if url.host:
            conn += ["--host", str(url.host)]
        if url.port:
            conn += ["--port", str(url.port)]
        if url.username:
            conn += ["--username", str(url.username)]
        if url.database:
            conn += ["--dbname", str(url.database)]
        if url.password:
            env["PGPASSWORD"] = url.password
        cmd += conn
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
        if proc.returncode != 0:
            raise BackupError(f"pg_dump failed: {proc.stderr.strip()[:500]}")
        return dump_path

    def _dump_sqlite(self, workdir: str) -> str:
        """Dev/test fallback: snapshot the SQLite database via the sqlite3
        backup API (works for file-based and in-memory databases alike)."""
        import sqlite3

        dump_path = os.path.join(workdir, "postgres.dump")  # same archive layout
        raw = engine.raw_connection()
        try:
            dbapi_conn = raw.connection  # unwrap SQLAlchemy fairy -> sqlite3.Connection
            src = sqlite3.connect(dump_path)
            try:
                dbapi_conn.backup(src)  # type: ignore[attr-defined]
            finally:
                src.close()
        finally:
            raw.close()
        return dump_path

    def _dump_database(self, workdir: str) -> str:
        url = str(engine.url)
        if url.startswith("postgresql"):
            return self._dump_postgres(workdir)
        if url.startswith("sqlite"):
            return self._dump_sqlite(workdir)
        raise BackupError(f"Unsupported database engine for backup: {url.split(':')[0]}")

    def _restore_postgres(self, dump_path: str) -> None:
        url = engine.url
        env = dict(os.environ)
        if url.password:
            env["PGPASSWORD"] = url.password
        # Drop and recreate the schema, then restore into the clean schema.
        # We connect to the same database (single-DB deployments) and use
        # pg_restore's --clean so it replaces existing objects.
        cmd = [
            "pg_restore",
            "--host", str(url.host or "localhost"),
            "--port", str(url.port or 5432),
            "--username", str(url.username or ""),
            "--dbname", str(url.database or ""),
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--single-transaction",
            dump_path,
        ]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
        if proc.returncode != 0:
            raise BackupError(f"pg_restore failed: {proc.stderr.strip()[:500]}")

    def _restore_sqlite(self, dump_path: str) -> None:
        """Restore a SQLite snapshot into the live engine via the backup API
        (works for file-based and in-memory databases)."""
        import sqlite3

        # NOTE: no engine.dispose() here — for in-memory SQLite the pooled
        # connection *is* the database; disposing would destroy it.
        raw = engine.raw_connection()
        try:
            dbapi_conn = raw.connection  # unwrap SQLAlchemy fairy -> sqlite3.Connection
            src = sqlite3.connect(dump_path)
            try:
                src.backup(dbapi_conn)  # type: ignore[attr-defined]
            finally:
                src.close()
        finally:
            raw.close()

    def _restore_database(self, dump_path: str) -> None:
        url = str(engine.url)
        if url.startswith("postgresql"):
            self._restore_postgres(dump_path)
        elif url.startswith("sqlite"):
            self._restore_sqlite(dump_path)
        else:
            raise BackupError(f"Unsupported database engine for restore: {url.split(':')[0]}")

    # --------------------------------------------------------------- sessions
    @staticmethod
    def _sessions_dir() -> str:
        return get_settings().sessions_dir

    def _collect_sessions_into(self, dest: str) -> int:
        sessions_root = self._sessions_dir()
        os.makedirs(dest, exist_ok=True)
        count = 0
        if os.path.isdir(sessions_root):
            for name in sorted(os.listdir(sessions_root)):
                path = os.path.join(sessions_root, name)
                if os.path.isfile(path) and (name.endswith(".session") or name.endswith(".session-journal")):
                    shutil.copy2(path, os.path.join(dest, name))
                    count += 1
        return count

    def _restore_sessions(self, workdir: str) -> int:
        sessions_root = self._sessions_dir()
        src = os.path.join(workdir, "sessions")
        os.makedirs(sessions_root, exist_ok=True)
        count = 0
        for name in sorted(os.listdir(src)):
            path = os.path.join(src, name)
            if os.path.isfile(path):
                shutil.copy2(path, os.path.join(sessions_root, name))
                count += 1
        return count

    @staticmethod
    def _live_session_count() -> int:
        root = BackupService._sessions_dir()
        if not os.path.isdir(root):
            return 0
        return sum(
            1
            for name in os.listdir(root)
            if name.endswith(".session") and os.path.isfile(os.path.join(root, name))
        )

    def _normalize_session_paths(self) -> int:
        """Re-point ``telegram_accounts.session_path`` at the CURRENT sessions
        dir (TZ §7: after a server migration the restored DB may carry absolute
        paths from the old machine; a stale path makes Telethon open an EMPTY
        session — i.e. silent loss of authorization).

        A row is re-pointed only when a session file with the same basename
        exists in the live sessions dir; otherwise the row is left untouched.
        Returns the number of rows updated.
        """
        from sqlalchemy import text

        sessions_root = os.path.abspath(self._sessions_dir())
        available = {
            name for name in os.listdir(sessions_root)
            if name.endswith(".session")
        } if os.path.isdir(sessions_root) else set()
        if not available:
            return 0

        db = _db()
        updated = 0
        try:
            rows = db.execute(
                text("SELECT id, session_path FROM telegram_accounts WHERE session_path IS NOT NULL")
            ).all()
            for row_id, path in rows:
                if not path or os.path.abspath(path) == sessions_root:
                    continue
                basename = os.path.basename(path)
                if basename in available:
                    db.execute(
                        text("UPDATE telegram_accounts SET session_path = :p WHERE id = :i"),
                        {"p": os.path.join(sessions_root, basename), "i": row_id},
                    )
                    updated += 1
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            raise
        finally:
            db.close()
        if updated:
            logger.info("restore: re-pointed %d session path(s) to %s", updated, sessions_root)
        return updated

    # --------------------------------------------------------------- metadata
    # Settings/secrets that are REQUIRED to decrypt or use data carried by the
    # archive on another server (TZ §16). Secrets are exported to the snapshot
    # only when explicitly enabled — a backup containing Telegram sessions must
    # be treated as confidential either way.
    _SNAPSHOT_ENV_KEYS = (
        "SECRET_KEY",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_PROXY_ENABLED",
        "TELEGRAM_PROXY_HOST",
        "TELEGRAM_PROXY_PORT",
        "TELEGRAM_PROXY_SECRET",
        "SESSIONS_DIR",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "STORYWATCHER_API_TOKEN",
        "BACKUP_AUTO_PASSWORD",
        # VPN: without the subscription URL the new server's vpn container has
        # no working proxy -> worker cannot reach Telegram -> restored sessions
        # appear "dead" even though they are perfectly valid.
        "VPN_SUBSCRIPTION_URL",
    )

    def _collect_config(self, workdir: str) -> dict:
        """Snapshot the environment/config needed to run the restored data.

        NOTE: the *database URL itself* is deliberately NOT carried over: the
        new server's Postgres credentials may differ, and compose sets them
        from its own .env. What matters is that data-affecting secrets
        (SECRET_KEY for token validity, TELEGRAM_API_* for session auth) are
        preserved so the restore works without re-authorization.
        """
        include_secrets = os.environ.get("BACKUP_SNAPSHOT_SECRETS", "1") not in ("0", "false", "False")
        config: dict[str, object] = {}
        for key in self._SNAPSHOT_ENV_KEYS:
            val = os.environ.get(key)
            if val is None or val == "":
                continue
            if not include_secrets and ("KEY" in key or "SECRET" in key or "TOKEN" in key or "HASH" in key or "PASSWORD" in key):
                config[key] = "__REDACTED__"
            else:
                config[key] = val
        cfg = get_settings()
        config["_derived"] = {
            "sessions_dir": cfg.sessions_dir,
            "telegram_proxy_enabled": cfg.telegram_proxy_enabled,
        }
        path = os.path.join(workdir, "app-config.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
        return config

    def _collect_metadata(self, workdir: str) -> dict:
        from sqlalchemy import inspect

        insp = inspect(engine)
        tables = sorted(insp.get_table_names())
        metadata = {
            "application": "TG Story Watcher",
            "application_version": self._app_version(),
            "created_at": _now_iso(),
            "database_type": "postgresql" if str(engine.url).startswith("postgresql") else "sqlite",
            "schema_version": "1",
            "tables": tables,
        }
        with open(os.path.join(workdir, "version.json"), "w") as fh:
            json.dump(metadata, fh, indent=2)
        return metadata

    @staticmethod
    def _app_version() -> str:
        try:
            from importlib.metadata import version as _v

            return _v("storywatcher")
        except Exception:  # noqa: BLE001
            return "0.1.0"

    # ------------------------------------------------------------- create
    def create_backup(
        self,
        op_id: str,
        password: str | None = None,
        created_by: str | None = None,
    ) -> str:
        """Create a backup archive asynchronously. Returns the backup id."""

        def _run() -> None:
            with _op_lock:
                backup_id = op_id
                db = _db()
                workdir = tempfile.mkdtemp(prefix="tgsw-backup-")
                archive_path: str | None = None
                try:
                    self._start_op(op_id)
                    self._set_progress(op_id, 5, "validate")
                    url = str(engine.url)

                    record = BackupRecord(
                        id=backup_id,
                        filename="",
                        created_at=datetime.now(timezone.utc),
                        encrypted=bool(password),
                        storage_path="",
                        status="CREATING",
                        origin="CREATE",
                        metadata_json=None,
                    )
                    db.add(record)
                    db.commit()

                    # 1) Database dump
                    self._set_progress(op_id, 10, "database")
                    dump_path = self._dump_database(workdir)
                    db_dir = os.path.join(workdir, "database")
                    os.makedirs(db_dir, exist_ok=True)
                    shutil.move(dump_path, os.path.join(db_dir, "postgres.dump"))

                    # 2) Sessions (archive layout: telegram/sessions/*)
                    self._set_progress(op_id, 45, "sessions")
                    sessions_dest = os.path.join(workdir, "telegram", "sessions")
                    os.makedirs(sessions_dest, exist_ok=True)
                    sessions_count = self._collect_sessions_into(sessions_dest)

                    # 3) Config snapshot + metadata + manifest
                    self._set_progress(op_id, 50, "config")
                    self._collect_config(os.path.join(workdir, "config"))

                    self._set_progress(op_id, 55, "metadata")
                    metadata = self._collect_metadata(workdir)

                    from sqlalchemy import inspect, text

                    insp = inspect(engine)
                    users_count = db.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0
                    accounts_count = db.execute(text("SELECT COUNT(*) FROM telegram_accounts")).scalar() or 0
                    manifest = {
                        "format_version": FORMAT_VERSION,
                        "application": "TG Story Watcher",
                        "application_version": metadata["application_version"],
                        "created_at": _now_iso(),
                        "database_type": metadata["database_type"],
                        "database_version": self._database_version(),
                        "schema_version": "1",
                        "users": users_count,
                        "telegram_accounts": accounts_count,
                        "telegram_sessions": sessions_count,
                        "components": ["database", "telegram_sessions", "application_config", "metadata"],
                        "checksum_algorithm": "sha256",
                    }
                    with open(os.path.join(workdir, MANIFEST_NAME), "w") as fh:
                        json.dump(manifest, fh, indent=2)

                    # 4) Checksums
                    self._set_progress(op_id, 65, "checksums")
                    checksums = []
                    for root, _dirs, files in os.walk(workdir):
                        for f in sorted(files):
                            p = os.path.join(root, f)
                            rel = os.path.relpath(p, workdir)
                            if rel == CHECKSUMS_NAME:
                                continue
                            checksums.append(f"{crypto.sha256_file(p)}  {rel}")
                    with open(os.path.join(workdir, CHECKSUMS_NAME), "w") as fh:
                        fh.write("\n".join(checksums) + "\n")

                    # 5) Archive (everything under backup/ root inside the tar)
                    self._set_progress(op_id, 75, "archive")
                    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
                    filename = f"tg-story-watcher-backup-{ts}.tar.gz"
                    archive_path = os.path.join(tempfile.gettempdir(), filename)
                    with tarfile.open(archive_path, "w:gz") as tar:
                        for name in sorted(os.listdir(workdir)):
                            tar.add(
                                os.path.join(workdir, name),
                                arcname=f"{ARCHIVE_MEMBER_ROOT}{name}",
                            )

                    # 6) Encrypt (in memory; archives may be large, but AES-GCM
                    #    on the whole buffer is acceptable up to ~1-2 GB)
                    self._set_progress(op_id, 85, "encrypt")
                    final_path = archive_path
                    if password:
                        with open(archive_path, "rb") as fh:
                            raw = fh.read()
                        enc_path = archive_path + ".enc"
                        with open(enc_path, "wb") as fh:
                            fh.write(crypto.encrypt_stream(raw, password))
                        os.remove(archive_path)
                        final_path = enc_path

                    checksum = crypto.sha256_file(final_path)
                    size = os.path.getsize(final_path)

                    # 7) Store
                    self._set_progress(op_id, 92, "store")
                    key = f"{backup_id}/{filename}" + (".enc" if password else "")
                    final_name = filename + (".enc" if password else "")
                    self.storage.save(key, final_path)
                    archive_path = None  # moved into storage

                    db = _db()
                    record = db.get(BackupRecord, backup_id)
                    if record is not None:
                        record.filename = final_name
                        record.storage_path = key
                        record.size = size
                        record.checksum = checksum
                        record.application_version = manifest["application_version"]
                        record.schema_version = str(manifest["schema_version"])
                        record.metadata_json = json.dumps(
                            {
                                "users": manifest["users"],
                                "telegram_accounts": manifest["telegram_accounts"],
                                "telegram_sessions": manifest["telegram_sessions"],
                            }
                        )
                        record.status = "READY"
                        db.commit()

                    self._finish_op(op_id, "SUCCESS")
                    logger.info("backup %s created (%s bytes, encrypted=%s)", backup_id, size, bool(password))
                except Exception as exc:  # noqa: BLE001
                    logger.exception("backup %s failed", backup_id)
                    err_db = _db()
                    try:
                        rec = err_db.get(BackupRecord, backup_id)
                        if rec is not None:
                            rec.status = "FAILED"
                            err_db.commit()
                    finally:
                        err_db.close()
                    self._finish_op(op_id, "FAILED", str(exc))
                finally:
                    shutil.rmtree(workdir, ignore_errors=True)
                    if archive_path and os.path.isfile(archive_path):
                        try:
                            os.remove(archive_path)
                        except OSError:
                            pass

        threading.Thread(target=_run, daemon=True, name=f"backup-{op_id[:8]}").start()
        return op_id

    def _database_version(self) -> str:
        try:
            with engine.connect() as conn:
                from sqlalchemy import text

                row = conn.execute(text("SELECT version()")).scalar()
                if row:
                    return str(row).split()[1]
        except Exception:  # noqa: BLE001
            pass
        return "unknown"

    # ------------------------------------------------------------- validate
    def validate_backup(self, op_id: str, backup_id: str, password: str | None = None) -> dict:
        """Validate an archive: manifest, checksums, sessions, compatibility."""

        def _run() -> None:
            with _op_lock:
                try:
                    self._start_op(op_id)
                    self._set_progress(op_id, 10, "open")
                    db = _db()
                    record = db.get(BackupRecord, backup_id)
                    db.close()
                    if record is None:
                        raise BackupError("backup record not found")

                    self._set_progress(op_id, 25, "decrypt")
                    stored_path = self.storage.open(record.storage_path)
                    workdir = tempfile.mkdtemp(prefix="tgsw-validate-")
                    try:
                        archive = stored_path
                        if password:
                            with open(stored_path, "rb") as fh:
                                raw = fh.read()
                            plain = crypto.decrypt_stream(raw, password)
                            archive = os.path.join(workdir, "plain.tar.gz")
                            with open(archive, "wb") as fh:
                                fh.write(plain)
                        elif record.encrypted:
                            raise BackupError("backup is encrypted: password required")

                        self._set_progress(op_id, 45, "archive")
                        if not tarfile.is_tarfile(archive):
                            raise BackupError("not a valid tar.gz archive")
                        with tarfile.open(archive, "r:gz") as tar:
                            names = tar.getnames()
                            prefix_ok = all(n.startswith(ARCHIVE_MEMBER_ROOT) or n == ARCHIVE_MEMBER_ROOT.rstrip("/") for n in names)
                            if not prefix_ok:
                                raise BackupError("unexpected archive layout")

                            def _read(member: str) -> dict | str | None:
                                m = tar.extractfile(f"{ARCHIVE_MEMBER_ROOT}{member}")
                                if m is None:
                                    return None
                                return m.read()

                            manifest_raw = _read(MANIFEST_NAME)
                            if not manifest_raw:
                                raise BackupError("manifest.json missing")
                            manifest = json.loads(manifest_raw)
                            if int(manifest.get("format_version", 0)) > FORMAT_VERSION:
                                raise BackupError(
                                    f"backup format {manifest.get('format_version')} is newer than supported {FORMAT_VERSION}"
                                )

                            self._set_progress(op_id, 60, "checksums")
                            sums_raw = _read(CHECKSUMS_NAME)
                            checksum_errors = 0
                            checked = 0
                            if sums_raw:
                                for line in sums_raw.decode().splitlines():
                                    if not line.strip():
                                        continue
                                    digest, _, rel = line.partition("  ")
                                    m = tar.extractfile(f"{ARCHIVE_MEMBER_ROOT}{rel}")
                                    if m is None:
                                        checksum_errors += 1
                                        continue
                                    import hashlib

                                    h = hashlib.sha256(m.read()).hexdigest()
                                    checked += 1
                                    if h != digest:
                                        checksum_errors += 1

                            self._set_progress(op_id, 80, "sessions")
                            sessions = [n for n in names if n.startswith(f"{ARCHIVE_MEMBER_ROOT}{SESSIONS_PREFIX}") and n.endswith(".session")]
                            has_dump = any(n == f"{ARCHIVE_MEMBER_ROOT}{DB_DUMP_NAME}" for n in names)
                            has_config = any(n == f"{ARCHIVE_MEMBER_ROOT}{CONFIG_NAME}" for n in names)
                            manifest_sessions = manifest.get("telegram_sessions")
                            session_parity = (
                                None
                                if manifest_sessions is None
                                else (len(sessions) == int(manifest_sessions))
                            )

                            result = {
                                "valid": checksum_errors == 0 and has_dump,
                                "integrity": "VALID" if checksum_errors == 0 else f"{checksum_errors} mismatches",
                                "database": "VALID" if has_dump else "MISSING",
                                "config": "PRESENT" if has_config else "MISSING",
                                "sessions": len(sessions),
                                "session_parity": session_parity,
                                "manifest": manifest,
                                "checked_files": checked,
                                "compatibility": "COMPATIBLE",
                            }
                            self._set_progress(op_id, 100, "done")
                            self._finish_op(op_id, "SUCCESS")
                            # Attach result to the operation row for the API.
                            self._store_op_result(op_id, result)
                    finally:
                        shutil.rmtree(workdir, ignore_errors=True)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("backup validation %s failed: %s", backup_id, exc)
                    self._finish_op(op_id, "FAILED", str(exc))

        threading.Thread(target=_run, daemon=True, name=f"validate-{op_id[:8]}").start()
        return op_id

    def _store_op_result(self, op_id: str, result: dict) -> None:
        db = _db()
        try:
            op = db.get(BackupOperation, op_id)
            if op is not None:
                op.error = None
                op.stage = json.dumps(result)[:2000]
                db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------- restore
    def _extract_verified(
        self,
        archive: str,
        workdir: str,
        password: str | None,
        record: BackupRecord,
        set_progress,
    ) -> tuple[str, dict, list[str]]:
        """Decrypt, extract and FULLY verify an archive before anything on the
        live system is touched (TZ §27/§31: never begin a restore from an
        unverified archive; fail atomically on the first inconsistency).

        Returns (inner_dir, manifest, session_member_names).
        """
        set_progress(15, "decrypt")
        if password:
            with open(archive, "rb") as fh:
                raw = fh.read()
            plain = crypto.decrypt_stream(raw, password)
            archive = os.path.join(workdir, "plain.tar.gz")
            with open(archive, "wb") as fh:
                fh.write(plain)
        elif record.encrypted:
            raise BackupError("backup is encrypted: password required")

        set_progress(25, "verify")
        if not tarfile.is_tarfile(archive):
            raise BackupError("not a valid tar.gz archive")
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for m in members:
                if m.name.startswith("/") or ".." in m.name:
                    raise BackupError("unsafe archive member path")
            names = [m.name for m in members]
            if not all(n.startswith(ARCHIVE_MEMBER_ROOT) for n in names):
                raise BackupError("unexpected archive layout")

            def _read(member: str) -> bytes | None:
                try:
                    f = tar.extractfile(f"{ARCHIVE_MEMBER_ROOT}{member}")
                except KeyError:
                    return None
                return f.read() if f is not None else None

            manifest_raw = _read(MANIFEST_NAME)
            if not manifest_raw:
                raise BackupError("manifest.json missing from archive")
            try:
                manifest = json.loads(manifest_raw)
            except ValueError as exc:
                raise BackupError("manifest.json is not valid JSON") from exc
            fmt = int(manifest.get("format_version", 0))
            if fmt > FORMAT_VERSION:
                raise BackupError(
                    f"backup format {fmt} is newer than supported {FORMAT_VERSION}"
                )
            if fmt < FORMAT_VERSION:
                raise BackupError(
                    f"backup format {fmt} is older than supported {FORMAT_VERSION}"
                )

            # 1) Integrity: every checksummed file must match (TZ §19).
            set_progress(35, "checksums")
            sums_raw = _read(CHECKSUMS_NAME)
            if not sums_raw:
                raise BackupError("checksums.sha256 missing from archive")
            import hashlib

            mismatched: list[str] = []
            for line in sums_raw.decode().splitlines():
                if not line.strip():
                    continue
                digest, _, rel = line.partition("  ")
                data = _read(rel)
                if data is None or hashlib.sha256(data).hexdigest() != digest:
                    mismatched.append(rel)
            if mismatched:
                raise BackupError(
                    f"archive integrity check failed ({len(mismatched)} file(s)): "
                    + ", ".join(mismatched[:5])
                )

            # 2) Required components (TZ §17).
            if _read(DB_DUMP_NAME) is None:
                raise BackupError("database dump missing from archive")
            session_members = [
                n[len(ARCHIVE_MEMBER_ROOT) + len(SESSIONS_PREFIX):]
                for n in names
                if n.startswith(f"{ARCHIVE_MEMBER_ROOT}{SESSIONS_PREFIX}") and n.endswith(".session")
            ]
            expected = manifest.get("telegram_sessions")
            if expected is not None and len(session_members) != int(expected):
                raise BackupError(
                    f"session count mismatch: manifest says {expected}, archive contains {len(session_members)}"
                )

        set_progress(45, "extract")
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(workdir, members=tar.getmembers())
        inner = os.path.join(workdir, ARCHIVE_MEMBER_ROOT.rstrip("/"))
        if not os.path.isdir(inner):
            raise BackupError("unexpected archive layout")
        return inner, manifest, session_members

    def restore_backup(
        self,
        op_id: str,
        backup_id: str,
        password: str | None = None,
        created_by: str | None = None,
    ) -> None:
        """Restore a backup: DB + sessions. The caller (API layer) is responsible
        for creating a pre-restore backup and stopping/pausing the worker."""

        def _run() -> None:
            with _op_lock:
                try:
                    self._start_op(op_id)
                    db = _db()
                    record = db.get(BackupRecord, backup_id)
                    db.close()
                    if record is None:
                        raise BackupError("backup record not found")

                    stored_path = self.storage.open(record.storage_path)
                    workdir = tempfile.mkdtemp(prefix="tgsw-restore-")
                    try:
                        inner, manifest, session_members = self._extract_verified(
                            stored_path, workdir, password, record,
                            lambda p, s=None: self._set_progress(op_id, p, s),
                        )
                        sessions_before = self._live_session_count()

                        # 1) Database restore (all-or-nothing via --single-transaction)
                        self._set_progress(op_id, 55, "database")
                        dump_path = os.path.join(inner, DB_DUMP_NAME)
                        self._restore_database(dump_path)

                        # 2) Sessions restore
                        self._set_progress(op_id, 75, "sessions")
                        sessions_src = os.path.join(inner, "telegram/sessions")
                        count = 0
                        if os.path.isdir(sessions_src):
                            os.makedirs(self._sessions_dir(), exist_ok=True)
                            for name in sorted(os.listdir(sessions_src)):
                                p = os.path.join(sessions_src, name)
                                if os.path.isfile(p):
                                    shutil.copy2(p, os.path.join(self._sessions_dir(), name))
                                    count += 1

                        # 3) Re-point DB session paths at the live sessions dir
                        # (server migration may have changed SESSIONS_DIR).
                        self._set_progress(op_id, 82, "session paths")
                        re_pointed = self._normalize_session_paths()

                        # 4) Verify DB is readable and expected data is back.
                        self._set_progress(op_id, 85, "verify")
                        from sqlalchemy import inspect, text

                        insp = inspect(engine)
                        tables = set(insp.get_table_names())
                        required = {"users", "telegram_accounts"}
                        if not required.issubset(tables):
                            raise BackupError(f"restored database missing tables: {required - tables}")

                        db = _db()
                        try:
                            users = db.execute(text("SELECT COUNT(*) FROM users")).scalar()
                            accounts = db.execute(text("SELECT COUNT(*) FROM telegram_accounts")).scalar()
                        finally:
                            db.close()

                        # 4) Session parity: after the restore the live sessions
                        # dir must contain at least everything the archive had
                        # (TZ §7: session count before == after).
                        sessions_after = self._live_session_count()
                        expected_sessions = len(session_members)
                        if sessions_after < expected_sessions:
                            raise BackupError(
                                f"session restore incomplete: expected {expected_sessions}, found {sessions_after}"
                            )

                        # 5) Persist the result OUTSIDE the database: a successful
                        # restore has just replaced the DB (and with it this op
                        # row), so the API would otherwise report the restore as
                        # lost/unknown.
                        result = {
                            "restored_users": users,
                            "restored_accounts": accounts,
                            "restored_sessions": count,
                            "live_session_files": sessions_after,
                            "expected_sessions": expected_sessions,
                            "sessions_before": sessions_before,
                            "session_paths_repointed": re_pointed,
                            "database_type": manifest.get("database_type", "unknown"),
                            "manifest_created_at": manifest.get("created_at"),
                        }
                        self._set_progress(op_id, 100, "done")
                        self._finish_op(op_id, "SUCCESS")
                        try:
                            self._store_op_result(op_id, result)
                        except Exception:  # noqa: BLE001
                            logger.debug("op row gone after DB restore (expected)")
                        from .storage import write_meta_json

                        write_meta_json(f"restore-{op_id}.json", {"op_id": op_id, "backup_id": backup_id, "status": "SUCCESS", **result})
                        logger.info("restore %s completed: %s", op_id, result)
                    finally:
                        shutil.rmtree(workdir, ignore_errors=True)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("restore %s failed", op_id)
                    self._finish_op(op_id, "FAILED", str(exc))
                    try:
                        from .storage import write_meta_json

                        write_meta_json(f"restore-{op_id}.json", {"op_id": op_id, "backup_id": backup_id, "status": "FAILED", "error": str(exc)[:500]})
                    except Exception:  # noqa: BLE001
                        pass

        threading.Thread(target=_run, daemon=True, name=f"restore-{op_id[:8]}").start()

    # ------------------------------------------------------------- retention
    def apply_retention(self, keep: int) -> int:
        """Delete the oldest backups beyond ``keep`` most recent. Returns count."""
        db = _db()
        try:
            records = (
                db.query(BackupRecord)
                .filter(BackupRecord.status == "READY")
                .order_by(BackupRecord.created_at.desc())
                .all()
            )
            removed = 0
            for rec in records[keep:]:
                try:
                    self.storage.delete(rec.storage_path)
                except FileNotFoundError:
                    pass
                rec.status = "DELETED"
                removed += 1
            db.commit()
            return removed
        finally:
            db.close()
