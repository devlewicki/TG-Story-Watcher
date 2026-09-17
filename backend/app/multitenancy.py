from __future__ import annotations
import base64, hashlib, hmac, json, secrets, time
from fastapi import Header, HTTPException
from .config import get_settings

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16); digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    return "pbkdf2_sha256$310000$%s$%s" % (base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())
def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_raw, digest_raw = encoded.split("$", 3); digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt_raw), int(rounds))
        return scheme == "pbkdf2_sha256" and hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), digest_raw)
    except (ValueError, TypeError): return False
def create_user_token(user_id: int) -> str:
    now = int(time.time())
    payload = base64.urlsafe_b64encode(json.dumps({
        "user_id": user_id, "iat": now, "exp": now + 86400 * 30,
    }, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"user.{payload}.{hmac.new(get_settings().secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()}"
def user_id_from_token(token: str | None) -> int | None:
    try:
        if not token or not token.startswith("user."): return None
        _, payload, signature = token.split(".", 2); expected = hmac.new(get_settings().secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not hmac.compare_digest(signature, expected): return None
        if int(data["exp"]) <= time.time(): return None
        uid = int(data["user_id"])
        # Per-user token revocation + existence check (best-effort: if the DB
        # is unavailable, the token passes through). The row-existence check
        # rejects tokens issued to a user that was deleted by an admin, which
        # otherwise manifests as FK-violation 500s on the next write.
        try:
            from .db import SessionLocal
            from .models import SettingsStore as _SS
            from .models import User as _User
            _db = SessionLocal()
            try:
                _revoked = _db.query(_SS.value).filter_by(key=f"user:{uid}:token_revoked_at").first()
                if _revoked is not None:
                    revoked_at = int(_revoked.value)
                    iat = data.get("iat")
                    if iat is not None:
                        # Tokens carry an issued-at claim: revocation kills any
                        # token that was not issued strictly after the revocation
                        # point (same-second issuance also counts as revoked).
                        if int(iat) <= revoked_at:
                            return None
                    elif int(data["exp"]) <= revoked_at:
                        # Legacy tokens (no iat, issued before this check was
                        # added): keep the old expiry comparison.
                        return None
                if _db.get(_User, uid) is None:
                    return None
            finally:
                _db.close()
        except Exception:
            pass  # best-effort: if DB unavailable, allow the token through
        return uid
    except (ValueError, KeyError, TypeError, json.JSONDecodeError): return None


def revoke_user_tokens(user_id: int) -> None:
    """Record the current time as the revocation point for this user.

    Callers should persist this via SettingsStore and/or rotate
    ``secret_key`` to invalidate existing tokens.
    """
    from .db import SessionLocal
    from .models import SettingsStore as _SS
    import json as _json
    db = SessionLocal()
    try:
        key = f"user:{user_id}:token_revoked_at"
        row = db.query(_SS).filter_by(key=key).first()
        now_str = str(int(time.time()))
        if row is None:
            db.add(_SS(key=key, value=now_str))
        else:
            row.value = now_str
        db.commit()
    finally:
        db.close()


def require_user(x_api_token: str | None = Header(default=None)) -> int:
    user_id = user_id_from_token(x_api_token)
    if user_id is None: raise HTTPException(401, "Требуется вход пользователя")
    return user_id
