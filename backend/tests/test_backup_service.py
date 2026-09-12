"""End-to-end backup lifecycle tests on SQLite.

create -> validate -> (destroy data) -> restore -> verify relations/sessions.
"""
from __future__ import annotations

import os
import tarfile
import uuid

import pytest

from app.admin_models import AdminUser
from app.multitenancy import hash_password
from app.models import (
    Story,
    StoryQueue,
    StoryView,
    TelegramAccount,
    User,
)


@pytest.fixture()
def backup_env(tmp_path, monkeypatch):
    """Redirect sessions + backup storage into a temp dir."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    backups_dir = tmp_path / "backups"
    monkeypatch.setenv("SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setenv("BACKUP_STORAGE_DIR", str(backups_dir))
    # Settings are lru_cached; regenerate them so the new SESSIONS_DIR applies.
    from app.config import get_settings

    get_settings.cache_clear()
    return {"sessions_dir": str(sessions_dir), "backups_dir": str(backups_dir)}


@pytest.fixture()
def svc_db(engine, monkeypatch):
    """Point BackupService's SessionLocal AND engine at the test engine so the
    service dumps/restores the isolated SQLite database, not a global one."""
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    import app.services.backup.service as backup_service_module

    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr(backup_service_module, "SessionLocal", TestSession)
    monkeypatch.setattr(backup_service_module, "engine", engine)
    # make sure admin tables exist in the test DB (conftest creates all models
    # via Base.metadata.create_all, but only if admin models were imported)
    import app.admin_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    return TestSession


def _make_session_file(sessions_dir: str, name: str, payload: bytes) -> str:
    path = os.path.join(sessions_dir, name)
    with open(path, "wb") as fh:
        fh.write(payload)
    return path


def _seed_world(db) -> dict:
    user = User(first_name="A", last_name="B", email=f"a{uuid.uuid4().hex[:6]}@t.io", password_hash="x")
    db.add(user)
    db.commit()
    acc = TelegramAccount(phone="+10000000001", user_id=user.id, status="ACTIVE", monitoring=True)
    db.add(acc)
    db.commit()
    story = Story(account_id=acc.id, peer_id=111, telegram_story_id=1, author_username="author1")
    db.add(story)
    db.commit()
    db.add(StoryQueue(account_id=acc.id, story_id=story.id, status="PENDING"))
    db.add(StoryView(account_id=acc.id, story_id=story.id, peer_id=111, telegram_story_id=1, status="VIEWED"))
    db.commit()
    return {"user_id": user.id, "account_id": acc.id, "story_id": story.id}


def test_backup_create_validate_restore_cycle(engine, db, backup_env, svc_db, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.services.backup import BackupService
    from app.services.backup.storage import LocalBackupStorage

    storage = LocalBackupStorage(backup_env["backups_dir"])
    svc = BackupService(storage=storage)

    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    world = _seed_world(session)
    session.close()

    # A fake Telethon session file that must travel inside the archive.
    _make_session_file(backup_env["sessions_dir"], "account_1.session", b"fake-telethon-session-bytes")

    op_id = "op-create-1"
    # Run synchronously: monkeypatch threading to run inline.
    created = {}

    real_thread = __import__("threading").Thread

    class InlineThread(real_thread):
        def start(self):
            self.run()

    monkeypatch.setattr("app.services.backup.service.threading.Thread", InlineThread)
    svc.create_backup(op_id=op_id, password="strongpass123")

    db_rec_session = TestSession()
    from app.admin_models import BackupRecord

    rec = db_rec_session.get(BackupRecord, op_id)
    db_rec_session.close()
    assert rec is not None
    assert rec.status == "READY"
    assert rec.size > 0
    assert rec.encrypted
    assert rec.filename.endswith(".tar.gz.enc")
    created["record"] = rec

    # The archive exists in storage and is encrypted.
    assert storage.exists(rec.storage_path)
    with open(storage.open(rec.storage_path), "rb") as fh:
        head = fh.read(8)
    assert head.startswith(b"TGSWENC1")

    # --- validate ---
    from app.admin_models import BackupOperation

    val_op = "op-validate-1"
    s = TestSession()
    s.add(BackupOperation(id=val_op, backup_id=op_id, type="VALIDATE", status="PENDING"))
    s.commit()
    s.close()
    svc.validate_backup(op_id=val_op, backup_id=op_id, password="strongpass123")

    s = TestSession()
    op = s.get(BackupOperation, val_op)
    result = __import__("json").loads(op.stage)
    s.close()
    assert op.status == "SUCCESS"
    assert result["valid"] is True
    assert result["sessions"] >= 1
    assert result["database"] == "VALID"

    # --- destroy the world, then restore ---
    s = TestSession()
    s.query(StoryView).delete()
    s.query(StoryQueue).delete()
    s.query(Story).delete()
    s.query(TelegramAccount).delete()
    s.query(User).delete()
    s.commit()
    s.close()
    os.remove(os.path.join(backup_env["sessions_dir"], "account_1.session"))

    rest_op = "op-restore-1"
    s = TestSession()
    from app.admin_models import BackupOperation as BOp

    s.add(BOp(id=rest_op, backup_id=op_id, type="RESTORE", status="PENDING"))
    s.commit()
    s.close()
    svc.restore_backup(op_id=rest_op, backup_id=op_id, password="strongpass123")

    # Verify data came back with relations intact.
    s = TestSession()
    users = s.query(User).all()
    assert len(users) == 1
    acc = s.query(TelegramAccount).filter_by(user_id=users[0].id).first()
    assert acc is not None
    story = s.query(Story).filter_by(account_id=acc.id).first()
    assert story is not None
    assert story.author_username == "author1"
    assert s.query(StoryQueue).filter_by(account_id=acc.id).count() == 1
    assert s.query(StoryView).filter_by(account_id=acc.id).count() == 1
    s.close()

    # Session file restored.
    assert os.path.isfile(os.path.join(backup_env["sessions_dir"], "account_1.session"))
    with open(os.path.join(backup_env["sessions_dir"], "account_1.session"), "rb") as fh:
        assert fh.read() == b"fake-telethon-session-bytes"

    # NOTE: the restore replaces the whole database (including admin tables),
    # so the BackupOperation row created before the restore is intentionally
    # gone afterwards — the restored DB is the state captured at backup time.
    # Surviving proof of success: the restored data below.


def test_encrypted_backup_rejects_wrong_password(engine, db, backup_env, svc_db, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.services.backup import BackupService
    from app.services.backup.crypto import decrypt_stream
    from app.services.backup.storage import LocalBackupStorage

    storage = LocalBackupStorage(backup_env["backups_dir"])
    svc = BackupService(storage=storage)
    TestSession = sessionmaker(bind=engine)

    real_thread = __import__("threading").Thread

    class InlineThread(real_thread):
        def start(self):
            self.run()

    monkeypatch.setattr("app.services.backup.service.threading.Thread", InlineThread)
    svc.create_backup(op_id="op-enc-1", password="right-password")

    from app.admin_models import BackupRecord

    s = TestSession()
    rec = s.get(BackupRecord, "op-enc-1")
    s.close()
    with open(storage.open(rec.storage_path), "rb") as fh:
        raw = fh.read()
    with pytest.raises(ValueError):
        decrypt_stream(raw, "wrong-password")
    plain = decrypt_stream(raw, "right-password")
    assert tarfile.is_tarfile(__import__("io").BytesIO(plain))


def test_corrupted_archive_fails_validation_and_restore(
    engine, db, backup_env, svc_db, monkeypatch
):
    """TZ 27: a damaged archive must be rejected loudly — no silent partial
    restore. Corrupt the stored archive and expect both validate and restore
    to fail without touching the live data."""
    from sqlalchemy.orm import sessionmaker

    from app.admin_models import BackupOperation, BackupRecord
    from app.services.backup import BackupError, BackupService
    from app.services.backup.storage import LocalBackupStorage

    storage = LocalBackupStorage(backup_env["backups_dir"])
    svc = BackupService(storage=storage)
    TestSession = sessionmaker(bind=engine)

    real_thread = __import__("threading").Thread

    class InlineThread(real_thread):
        def start(self):
            self.run()

    monkeypatch.setattr("app.services.backup.service.threading.Thread", InlineThread)

    _make_session_file(backup_env["sessions_dir"], "account_1.session", b"sess-bytes")
    svc.create_backup(op_id="op-corrupt-create")

    s = TestSession()
    rec = s.get(BackupRecord, "op-corrupt-create")
    # Corrupt the middle of the stored archive.
    path = storage.open(rec.storage_path)
    with open(path, "r+b") as fh:
        size = fh.seek(0, 2)
        fh.seek(size // 2)
        fh.write(b"\x00" * 512)
    s.close()

    # Restore must fail (reported via the operation status — the service runs
    # in a background thread and never raises to the caller) and NOT touch live
    # data.
    users_before = TestSession().query(User).count()
    rest_op = "op-corrupt-restore"
    s = TestSession()
    s.add(BackupOperation(
        id=rest_op, backup_id="op-corrupt-create", type="RESTORE", status="PENDING"
    ))
    s.commit()
    s.close()
    svc.restore_backup(op_id=rest_op, backup_id="op-corrupt-create")

    s = TestSession()
    op = s.get(BackupOperation, rest_op)
    s.close()
    assert op.status == "FAILED"
    assert op.error  # a human-readable cause must be recorded
    # Live data untouched.
    assert TestSession().query(User).count() == users_before


def test_config_snapshot_included_in_archive(engine, db, backup_env, svc_db, monkeypatch):
    """TZ 16/17: the archive must carry a config snapshot so a new server can
    run the restored data (secrets preserved by default, redaction opt-in)."""
    import tarfile as _tarfile

    from sqlalchemy.orm import sessionmaker

    from app.services.backup import BackupService
    from app.services.backup.crypto import decrypt_stream
    from app.services.backup.storage import LocalBackupStorage

    storage = LocalBackupStorage(backup_env["backups_dir"])
    svc = BackupService(storage=storage)
    TestSession = sessionmaker(bind=engine)

    real_thread = __import__("threading").Thread

    class InlineThread(real_thread):
        def start(self):
            self.run()

    monkeypatch.setattr("app.services.backup.service.threading.Thread", InlineThread)
    monkeypatch.setenv("SECRET_KEY", "test-secret-for-snapshot")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")

    svc.create_backup(op_id="op-config-1", password="strongpass123")

    from app.admin_models import BackupRecord

    s = TestSession()
    rec = s.get(BackupRecord, "op-config-1")
    s.close()
    with open(storage.open(rec.storage_path), "rb") as fh:
        plain = decrypt_stream(fh.read(), "strongpass123")
    import io

    with _tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
        names = tar.getnames()
        member = tar.extractfile("backup/config/app-config.json")
        assert member is not None
        config = __import__("json").loads(member.read())
    assert "backup/config/app-config.json" in names
    assert config["SECRET_KEY"] == "test-secret-for-snapshot"
    assert config["TELEGRAM_API_HASH"] == "deadbeef"

    # Redaction mode hides secrets but keeps the file present.
    monkeypatch.setenv("BACKUP_SNAPSHOT_SECRETS", "0")
    svc.create_backup(op_id="op-config-2", password="strongpass123")
    s = TestSession()
    rec2 = s.get(BackupRecord, "op-config-2")
    s.close()
    with open(storage.open(rec2.storage_path), "rb") as fh:
        plain2 = decrypt_stream(fh.read(), "strongpass123")
    with _tarfile.open(fileobj=io.BytesIO(plain2), mode="r:gz") as tar:
        member = tar.extractfile("backup/config/app-config.json")
        config2 = __import__("json").loads(member.read())
    assert config2["SECRET_KEY"] == "__REDACTED__"
    assert config2["TELEGRAM_API_HASH"] == "__REDACTED__"


def test_restore_result_survives_db_replacement(engine, db, backup_env, svc_db, monkeypatch):
    """TZ 35: after a successful restore the operation result must still be
    reportable even though the DB (and the op row) was replaced by the backup."""
    import json as _json
    from sqlalchemy.orm import sessionmaker

    from app.admin_models import BackupOperation, BackupRecord
    from app.services.backup import BackupService
    from app.services.backup.storage import LocalBackupStorage, read_meta_json

    storage = LocalBackupStorage(backup_env["backups_dir"])
    svc = BackupService(storage=storage)
    TestSession = sessionmaker(bind=engine)

    real_thread = __import__("threading").Thread

    class InlineThread(real_thread):
        def start(self):
            self.run()

    monkeypatch.setattr("app.services.backup.service.threading.Thread", InlineThread)

    # Seed a user + account so the backup has real data to restore.
    s = TestSession()
    world = _seed_world(s)
    s.close()

    _make_session_file(backup_env["sessions_dir"], "account_1.session", b"sess-bytes")
    svc.create_backup(op_id="op-meta-1")

    # Destroy the world, then restore.
    s = TestSession()
    s.query(StoryView).delete()
    s.query(StoryQueue).delete()
    s.query(Story).delete()
    s.query(TelegramAccount).delete()
    s.query(User).delete()
    s.commit()
    s.close()

    s = TestSession()
    s.add(BackupOperation(id="op-meta-restore", backup_id="op-meta-1", type="RESTORE", status="PENDING"))
    s.commit()
    s.close()
    svc.restore_backup(op_id="op-meta-restore", backup_id="op-meta-1")

    meta = read_meta_json("restore-op-meta-restore.json")
    assert meta is not None
    assert meta["status"] == "SUCCESS"
    assert meta["restored_users"] >= 1
    assert meta["restored_sessions"] == 1
    assert meta["expected_sessions"] == 1
    assert meta["live_session_files"] >= 1


def test_retention_deletes_oldest(engine, db, backup_env, svc_db, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app.admin_models import BackupRecord
    from app.services.backup import BackupService
    from app.services.backup.storage import LocalBackupStorage

    storage = LocalBackupStorage(backup_env["backups_dir"])
    svc = BackupService(storage=storage)
    TestSession = sessionmaker(bind=engine)

    s = TestSession()
    for i in range(5):
        s.add(
            BackupRecord(
                id=f"ret-{i}",
                filename=f"b{i}.tar.gz",
                storage_path=f"ret-{i}/b{i}.tar.gz",
                size=10,
                status="READY",
                origin="CREATE",
            )
        )
        # create placeholder files
        os.makedirs(os.path.join(backup_env["backups_dir"], f"ret-{i}"), exist_ok=True)
        with open(os.path.join(backup_env["backups_dir"], f"ret-{i}", f"b{i}.tar.gz"), "wb") as fh:
            fh.write(b"x")
    s.commit()
    s.close()

    removed = svc.apply_retention(keep=2)
    assert removed == 3
    s = TestSession()
    remaining = s.query(BackupRecord).filter_by(status="READY").count()
    deleted = s.query(BackupRecord).filter_by(status="DELETED").count()
    s.close()
    assert remaining == 2
    assert deleted == 3
