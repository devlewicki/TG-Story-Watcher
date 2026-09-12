"""Admin: backup & restore API."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...admin_auth import client_ip, current_admin, require_admin_permission, require_super_admin
from ...admin_models import AdminUser, BackupOperation, BackupRecord
from ...config import get_settings
from ...db import get_db
from ...models import SettingsStore
from ...services import admin_audit
from ...services.backup import BackupError, BackupService, FORMAT_VERSION
from ...workers import worker_control

router = APIRouter(tags=["admin-backups"])
Db = Annotated[Session, Depends(get_db)]

_upload_lock = threading.Lock()
_active_uploads = 0
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB
MAX_CONCURRENT_OPS = 1


def _svc() -> BackupService:
    return BackupService()


def _count_running_ops(db: Session) -> int:
    return (
        db.query(func.count(BackupOperation.id))
        .filter(BackupOperation.status.in_(("PENDING", "RUNNING")))
        .scalar()
        or 0
    )


@router.get("/backups")
def list_backups(
    db: Db,
    _admin: Annotated[AdminUser, Depends(current_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    q = db.query(BackupRecord).filter(BackupRecord.status != "DELETED")
    total = q.count()
    items = q.order_by(BackupRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_record_out(r) for r in items],
    }


def _record_out(r: BackupRecord) -> dict:
    meta = {}
    if r.metadata_json:
        try:
            meta = json.loads(r.metadata_json)
        except (ValueError, TypeError):
            meta = {}
    return {
        "id": r.id,
        "filename": r.filename,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "application_version": r.application_version,
        "schema_version": r.schema_version,
        "size": r.size,
        "checksum": r.checksum,
        "encrypted": r.encrypted,
        "status": r.status,
        "origin": r.origin,
        "users": meta.get("users"),
        "accounts": meta.get("telegram_accounts"),
        "sessions": meta.get("telegram_sessions"),
    }


class BackupCreateIn(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)


@router.post("/backups")
def create_backup(
    payload: BackupCreateIn,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    running = _count_running_ops(db)
    if running >= MAX_CONCURRENT_OPS:
        raise HTTPException(409, "another backup operation is already running")
    op_id = uuid.uuid4().hex
    op = BackupOperation(
        id=op_id, backup_id=None, type="CREATE", status="PENDING",
        created_by=admin.username,
    )
    db.add(op)
    db.commit()
    _svc().create_backup(op_id=op_id, password=payload.password, created_by=admin.username)
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="backup.create",
        target=f"operation:{op_id}", ip=client_ip(request),
        metadata={"encrypted": bool(payload.password)},
    )
    return {"operation_id": op_id, "backup_id": op_id, "status": "PENDING"}


@router.get("/backups/operations/{operation_id}")
def get_operation(
    operation_id: str,
    db: Db,
    _admin: Annotated[AdminUser, Depends(current_admin)],
):
    op = db.get(BackupOperation, operation_id)
    if op is None:
        # A successful RESTORE replaces the whole database, including this op
        # row — recover the persisted result from backup storage metadata.
        from ...services.backup.storage import read_meta_json

        meta = read_meta_json(f"restore-{operation_id}.json")
        if meta is not None:
            return {
                "id": operation_id,
                "backup_id": meta.get("backup_id"),
                "type": "RESTORE",
                "status": meta.get("status", "SUCCESS"),
                "progress": 100,
                "stage": None,
                "result": meta,
                "started_at": None,
                "finished_at": None,
                "error": meta.get("error"),
                "created_by": None,
            }
        raise HTTPException(404, "operation not found")
    result = None
    if op.stage and op.status == "SUCCESS" and op.type in ("VALIDATE", "RESTORE"):
        try:
            result = json.loads(op.stage)
        except (ValueError, TypeError):
            result = None
    if result is None and op.type == "RESTORE" and op.status == "SUCCESS":
        from ...services.backup.storage import read_meta_json

        result = read_meta_json(f"restore-{op.id}.json")
    return {
        "id": op.id,
        "backup_id": op.backup_id,
        "type": op.type,
        "status": op.status,
        "progress": op.progress,
        "stage": op.stage if op.type not in ("VALIDATE", "RESTORE") else None,
        "result": result,
        "started_at": op.started_at.isoformat() if op.started_at else None,
        "finished_at": op.finished_at.isoformat() if op.finished_at else None,
        "error": op.error,
        "created_by": op.created_by,
    }


@router.get("/backups/{backup_id}/download")
def download_backup(
    backup_id: str,
    db: Db,
    _admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
    request: Request = None,  # type: ignore[assignment]
):
    record = db.get(BackupRecord, backup_id)
    if record is None or record.status != "READY":
        raise HTTPException(404, "backup not found")
    if request is not None:
        admin_audit.audit(
            admin_id=_admin.id, admin_username=_admin.username, action="backup.download",
            target=f"backup:{backup_id}", ip=client_ip(request),
        )
    try:
        path = _svc().storage.open(record.storage_path)
    except FileNotFoundError:
        raise HTTPException(404, "backup file missing from storage")
    return FileResponse(path, filename=record.filename, media_type="application/gzip")


@router.post("/backups/upload")
async def upload_backup(
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
    file: UploadFile = File(...),
):
    global _active_uploads
    with _upload_lock:
        if _active_uploads >= MAX_CONCURRENT_OPS:
            raise HTTPException(409, "another backup upload is in progress")
        _active_uploads += 1
    backup_id = uuid.uuid4().hex
    op_id = uuid.uuid4().hex
    op = BackupOperation(
        id=op_id,
        backup_id=backup_id,
        type="UPLOAD",
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
        created_by=admin.username,
    )
    record = BackupRecord(
        id=backup_id, filename=file.filename or "uploaded-backup.tar.gz",
        created_at=datetime.now(timezone.utc), encrypted=False,
        storage_path="", status="UPLOADING", origin="UPLOAD",
    )
    db.add(op)
    db.add(record)
    db.commit()
    try:
        import tempfile

        svc = _svc()
        tmpdir = tempfile.mkdtemp(prefix="tgsw-upload-")
        tmp_path = os.path.join(tmpdir, file.filename or "backup.tar.gz")
        size = 0
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "backup file too large")
                out.write(chunk)
        key = f"{backup_id}/{os.path.basename(tmp_path)}"
        svc.storage.save(key, tmp_path)
        from ...services.backup.crypto import sha256_file

        record.filename = os.path.basename(key)
        record.storage_path = key
        record.size = size
        record.checksum = sha256_file(svc.storage.open(key))
        record.status = "READY"
        op.status = "SUCCESS"
        op.progress = 100
        op.finished_at = datetime.now(timezone.utc)
        db.commit()
        admin_audit.audit(
            admin_id=admin.id, admin_username=admin.username, action="backup.upload",
            target=f"backup:{backup_id}", ip=client_ip(request), metadata={"size": size},
        )
        return {"backup_id": backup_id, "operation_id": op_id, "size": size}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        record.status = "FAILED"
        op.status = "FAILED"
        op.error = str(exc)[:2000]
        op.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(400, f"upload failed: {exc}")
    finally:
        with _upload_lock:
            _active_uploads -= 1


class ValidateIn(BaseModel):
    password: str | None = Field(default=None, max_length=128)


@router.post("/backups/{backup_id}/validate")
def validate_backup(
    backup_id: str,
    payload: ValidateIn,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    record = db.get(BackupRecord, backup_id)
    if record is None:
        raise HTTPException(404, "backup not found")
    if record.encrypted and not payload.password:
        raise HTTPException(400, "password required for encrypted backup")
    running = _count_running_ops(db)
    if running >= MAX_CONCURRENT_OPS:
        raise HTTPException(409, "another backup operation is already running")
    op_id = uuid.uuid4().hex
    op = BackupOperation(id=op_id, backup_id=backup_id, type="VALIDATE", status="PENDING", created_by=admin.username)
    db.add(op)
    db.commit()
    _svc().validate_backup(op_id=op_id, backup_id=backup_id, password=payload.password)
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="backup.validate",
        target=f"backup:{backup_id}", ip=client_ip(request),
    )
    return {"operation_id": op_id, "status": "PENDING"}


class RestoreIn(BaseModel):
    password: str | None = Field(default=None, max_length=128)
    confirm: str = Field(min_length=1)
    create_pre_restore_backup: bool = True


@router.post("/backups/{backup_id}/restore")
async def restore_backup(
    backup_id: str,
    payload: RestoreIn,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_super_admin)],
):
    """Critical operation. Requires SUPER_ADMIN and typed confirmation RESTORE.

    Flow: pre-restore backup (optional) -> pause worker -> restore DB+sessions
    -> resume worker flag. Validation of the backup before restore is expected
    to have been done via /validate.
    """
    if payload.confirm != "RESTORE":
        raise HTTPException(400, "type RESTORE to confirm")
    record = db.get(BackupRecord, backup_id)
    if record is None or record.status != "READY":
        raise HTTPException(404, "backup not found")
    if record.encrypted and not payload.password:
        raise HTTPException(400, "password required for encrypted backup")
    running = _count_running_ops(db)
    if running >= MAX_CONCURRENT_OPS:
        raise HTTPException(409, "another backup operation is already running")

    pre_backup_id = None
    if payload.create_pre_restore_backup:
        pre_op = uuid.uuid4().hex
        db.add(BackupOperation(id=pre_op, backup_id=None, type="CREATE", status="PENDING", created_by=admin.username))
        db.commit()
        # Pre-restore backup is unencrypted (stays on the same server, in the
        # protected storage dir) so restore isn't blocked by a lost password.
        _svc().create_backup(op_id=pre_op, password=None, created_by=f"pre-restore:{admin.username}")
        pre_backup_id = pre_op

    op_id = uuid.uuid4().hex
    op = BackupOperation(id=op_id, backup_id=backup_id, type="RESTORE", status="PENDING", created_by=admin.username)
    db.add(op)
    db.commit()

    async def _run_restore() -> None:
        # Wait for the pre-restore backup to finish (if any), then pause the
        # worker so no Telegram operations or queue changes happen mid-restore.
        if pre_backup_id:
            from ...db import SessionLocal

            d = SessionLocal()
            try:
                for _ in range(600):  # up to ~10 min
                    op_row = d.get(BackupOperation, pre_backup_id)
                    if op_row is not None and op_row.status in ("SUCCESS", "FAILED"):
                        break
                    await asyncio.sleep(1)
            finally:
                d.close()
        worker_control.set_paused(True)
        await asyncio.sleep(2)  # let the worker finish its current cycle
        _svc().restore_backup(op_id=op_id, backup_id=backup_id, password=payload.password)
        # After success the API no longer touches the DB (restored schema may
        # replace admin tables); worker stays paused so the admin can verify
        # before resuming. Resume via /worker/resume.

    asyncio.create_task(_run_restore())
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="backup.restore",
        target=f"backup:{backup_id}", ip=client_ip(request),
        metadata={"pre_restore_backup": pre_backup_id},
    )
    return {"operation_id": op_id, "pre_restore_backup_operation": pre_backup_id, "status": "PENDING"}


@router.delete("/backups/{backup_id}")
def delete_backup(
    backup_id: str,
    request: Request,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    record = db.get(BackupRecord, backup_id)
    if record is None:
        raise HTTPException(404, "backup not found")
    svc = _svc()
    try:
        svc.storage.delete(record.storage_path)
    except FileNotFoundError:
        pass
    record.status = "DELETED"
    db.commit()
    admin_audit.audit(
        admin_id=admin.id, admin_username=admin.username, action="backup.delete",
        target=f"backup:{backup_id}", ip=client_ip(request),
    )
    return {"ok": True}


class RetentionIn(BaseModel):
    keep: int = Field(ge=1, le=100)


@router.post("/backups/retention")
def apply_retention(
    payload: RetentionIn,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
    request: Request = None,  # type: ignore[assignment]
):
    removed = _svc().apply_retention(payload.keep)
    if request is not None:
        admin_audit.audit(
            admin_id=admin.id, admin_username=admin.username, action="backup.retention",
            metadata={"keep": payload.keep, "removed": removed},
        )
    return {"ok": True, "removed": removed}


@router.get("/backups/settings")
def backup_settings(
    db: Db,
    _admin: Annotated[AdminUser, Depends(current_admin)],
):
    row = db.get(SettingsStore, "backup:auto")
    try:
        value = json.loads(row.value) if row else {}
    except (ValueError, TypeError):
        value = {}
    return {
        "auto_backup": value,
        "format_version": FORMAT_VERSION,
        "storage_dir": os.environ.get("BACKUP_STORAGE_DIR", "/data/backups"),
    }


class AutoBackupIn(BaseModel):
    enabled: bool = False
    schedule_hour_utc: int = Field(default=4, ge=0, le=23)
    retention: int = Field(default=7, ge=1, le=100)
    encrypted: bool = False


@router.put("/backups/settings")
def update_backup_settings(
    payload: AutoBackupIn,
    db: Db,
    admin: Annotated[AdminUser, Depends(require_admin_permission(write=True))],
):
    value = json.dumps(payload.model_dump())
    row = db.get(SettingsStore, "backup:auto")
    if row is None:
        db.add(SettingsStore(key="backup:auto", value=value))
    else:
        row.value = value
    db.commit()
    return {"ok": True, "auto_backup": payload.model_dump()}
