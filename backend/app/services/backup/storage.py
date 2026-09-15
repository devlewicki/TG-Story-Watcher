"""Backup storage abstraction.

The default backend writes archives to a local directory. Other backends
(S3/MinIO) can be added later without changing BackupService: they only need
to implement ``save``/``open``/``delete``/``exists``/``list_keys``.
"""
from __future__ import annotations

import json
import os
import shutil
from abc import ABC, abstractmethod


class BackupStorage(ABC):
    @abstractmethod
    def save(self, key: str, src_path: str) -> None: ...

    @abstractmethod
    def open(self, key: str) -> str:
        """Return a local filesystem path for the stored object (may be a temp copy)."""

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class LocalBackupStorage(BackupStorage):
    # Namespace for service-level metadata that must survive a full database
    # restore (the DB itself is replaced by the backup's contents).
    META_DIR = "_meta"

    @property
    def meta_dir(self) -> str:
        return os.path.join(self.root, self.META_DIR)
    def __init__(self, root: str):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _resolve(self, key: str) -> str:
        # Defensive: never escape the storage root.
        path = os.path.normpath(os.path.join(self.root, key))
        if not path.startswith(os.path.normpath(self.root)):
            raise ValueError("invalid backup key")
        return path

    def save(self, key: str, src_path: str) -> None:
        dst = self._resolve(key)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src_path, dst)

    def open(self, key: str) -> str:
        path = self._resolve(key)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        return path

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if os.path.isfile(path):
            os.remove(path)

    def exists(self, key: str) -> bool:
        return os.path.isfile(self._resolve(key))


def write_meta_json(name: str, payload: dict) -> None:
    """Persist a small JSON blob next to the archives (never inside the DB).

    Used so restore/validate results survive a successful restore, which by
    design replaces the whole database (including the backup_operations rows).
    """
    storage = default_storage()
    if not isinstance(storage, LocalBackupStorage):
        return
    os.makedirs(storage.meta_dir, exist_ok=True)
    # Defensive: refuse path traversal.
    if "/" in name or name in ("", ".", ".."):
        raise ValueError("invalid meta file name")
    tmp = os.path.join(storage.meta_dir, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(storage.meta_dir, name))


def read_meta_json(name: str) -> dict | None:
    storage = default_storage()
    if not isinstance(storage, LocalBackupStorage):
        return None
    if "/" in name or name in ("", ".", ".."):
        return None
    try:
        with open(os.path.join(storage.meta_dir, name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def default_storage() -> BackupStorage:
    root = os.environ.get("BACKUP_STORAGE_DIR", "/data/backups")
    if not os.path.isdir(os.path.dirname(root)) or root.startswith("."):
        # Local dev fallback: keep backups inside the project directory.
        root = os.path.join(os.getcwd(), "data", "backups")
    return LocalBackupStorage(root)
