"""Authenticated encryption for backup archives.

Uses standard, well-reviewed primitives only (AES-256-GCM via
``cryptography`` + PBKDF2-HMAC-SHA256 key derivation). No custom crypto.
"""
from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"TGSWENC1"
SALT_LEN = 16
NONCE_LEN = 12
KDF_ITERATIONS = 600_000


def derive_key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return kdf.derive(password.encode())


def encrypt_stream(data: bytes, password: str) -> bytes:
    """Encrypt bytes with AES-256-GCM. Output: MAGIC | salt | nonce | ct."""
    if not password:
        raise ValueError("encryption password must not be empty")
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = derive_key(password, salt)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return MAGIC + salt + nonce + ct


def decrypt_stream(data: bytes, password: str) -> bytes:
    if len(data) < len(MAGIC) + SALT_LEN + NONCE_LEN + 16:
        raise ValueError("encrypted backup is truncated or corrupted")
    if data[: len(MAGIC)] != MAGIC:
        raise ValueError("not an encrypted TG Story Watcher backup")
    salt = data[len(MAGIC) : len(MAGIC) + SALT_LEN]
    nonce = data[len(MAGIC) + SALT_LEN : len(MAGIC) + SALT_LEN + NONCE_LEN]
    ct = data[len(MAGIC) + SALT_LEN + NONCE_LEN :]
    key = derive_key(password, salt)
    try:
        return AESGCM(key).decrypt(nonce, ct, None)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("wrong backup password or corrupted archive") from exc


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
