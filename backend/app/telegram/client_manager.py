"""
Telegram client manager: creates, caches, and manages TelegramClient
instances for each account.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3 as _sqlite3
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Monkey-patch Telethon's SQLiteSession._cursor BEFORE any TelegramClient is
# created.  Telethon uses `sqlite3.connect(filename, check_same_thread=False)`
# which defaults to timeout=5s — far too short when the backend and worker
# share the same session file via a Docker volume.
# We override _cursor so every new connection gets timeout=60s and
# busy_timeout=60000ms (via PRAGMA).
# ---------------------------------------------------------------------------
from telethon.sessions.sqlite import SQLiteSession as _OrigSQLiteSession

_orig_cursor = _OrigSQLiteSession._cursor


def _patched_cursor(self):
    if self._conn is None:
        self._conn = _sqlite3.connect(
            self.filename,
            check_same_thread=False,
            timeout=60,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=60000")
    return self._conn.cursor()


_OrigSQLiteSession._cursor = _patched_cursor

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from ..config import get_settings
from ..models import AccountStatus

logger = logging.getLogger("storywatcher.telegram")
settings = get_settings()
_clients: dict[int, TelegramClient] = {}
_login_clients: dict[str, TelegramClient] = {}
_login_states: dict[str, "LoginState"] = {}


@dataclass
class LoginState:
    sent: dict = field(default_factory=dict)
    needs_password: bool = False


def _session_path(account_id: int) -> str:
    os.makedirs(settings.sessions_dir, exist_ok=True)
    return os.path.join(settings.sessions_dir, f"account_{account_id}.session")


def get_credentials(account):
    api_id = account.api_id or settings.telegram_api_id
    api_hash = account.api_hash or settings.telegram_api_hash
    if not api_id or not api_hash:
        raise ValueError("Telegram API credentials not configured")
    return int(api_id), api_hash


def _enable_sqlite_wal(path: str) -> None:
    """Enable WAL journal mode on a SQLite session file."""
    try:
        conn = _sqlite3.connect(path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.close()
    except Exception:
        logger.debug("Could not set WAL mode on %s", path, exc_info=True)


def _convert_string_to_sqlite(path: str) -> str:
    """Convert a StringSession file to an SQLite session file.

    ``finish_login`` saves sessions as base64 StringSession text files.
    Telethon treats a *path* argument as an SQLite session, while a
    *StringSession object* is in-memory-only and not persisted.  This means
    every restart loses the session state.

    This helper detects StringSession files, backs up the original, and uses
    a temporary TelegramClient with StringSession to fully load the state,
    then saves it to an SQLite session file.
    """
    try:
        backup = path + ".str.bak"
        if os.path.isfile(backup):
            with open(path, "rb") as fh:
                if fh.read(16).startswith(b"SQLite format 3"):
                    return path
            os.remove(path)
        with open(path, "r", encoding="utf-8") as fh:
            data = fh.read().strip()
        if not data:
            return path
        # Load StringSession object.
        str_sess = StringSession(data)
        # Back up the original text file.
        os.replace(path, backup)
        # Build a throw-away TelegramClient with the StringSession.
        # Connecting is NOT needed — Telethon loads session state lazily.
        # We just need to call session.save() to write to the new SQLite file.
        api_id, api_hash = _login_api()
        tmp_client = TelegramClient(str_sess, api_id, api_hash)
        # Force Telethon to load the session data by accessing internal state.
        # The StringSession already has dc_id, server, auth_key loaded from
        # the decoded data.
        # Now create an SQLite session at the target path and save the state.
        from telethon.sessions.sqlite import SQLiteSession
        sqlite_sess = SQLiteSession(path)
        # Copy ALL relevant state from StringSession.
        sqlite_sess._dc_id = str_sess.session._dc_id
        sqlite_sess._server_address = str_sess.session._server_address
        sqlite_sess._port = str_sess.session._port
        sqlite_sess._auth_key = str_sess.session._auth_key
        sqlite_sess._takeout_id = str_sess.session._takeout_id
        # Copy entities if any (may be dict or set).
        if hasattr(str_sess.session, '_entities'):
            _ents = str_sess.session._entities
            _iter = _ents if isinstance(_ents, (set, list)) else _ents.values()
            for entity in _iter:
                try:
                    sqlite_sess.process_entities(entity)
                except Exception:
                    pass
        sqlite_sess._update_session_table()
        sqlite_sess.save()
        sqlite_sess.close()
        logger.info("Converted StringSession -> SQLite for %s (backup: %s)", path, backup)
        return path
    except Exception as exc:
        logger.warning("String-to-SQLite conversion failed for %s: %s", path, exc)
        return path


def _read_session(path: str):
    if not os.path.isfile(path):
        return StringSession()
    with open(path, "rb") as file:
        raw = file.read()
    if raw.startswith(b"SQLite format 3"):
        _enable_sqlite_wal(path)
        return path
    # StringSession file — convert to SQLite so it persists across restarts.
    _convert_string_to_sqlite(path)
    _enable_sqlite_wal(path)
    return path


def build_client(account):
    api_id, api_hash = get_credentials(account)
    return TelegramClient(_read_session(account.session_path or _session_path(account.id)), api_id, api_hash)


async def get_client(account):
    if account.id not in _clients:
        _clients[account.id] = build_client(account)
    return _clients[account.id]


async def connect(account):
    client = await get_client(account)
    if not client.is_connected():
        await client.connect()
    return client


async def release_client(account_id: int):
    client = _clients.pop(account_id, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            logger.debug("Telegram client disconnect failed", exc_info=True)


async def drop_client(account_id: int):
    await release_client(account_id)


async def update_account_identity(account, client):
    me = await client.get_me()
    if me:
        account.telegram_user_id = getattr(me, "id", None)
        account.username = getattr(me, "username", None)
        account.first_name = getattr(me, "first_name", None)
        account.last_name = getattr(me, "last_name", None)
        account.phone = getattr(me, "phone", None) or account.phone


async def start_account(account):
    if not account.session_path:
        account.status = AccountStatus.DISCONNECTED.value
        account.monitoring = False
        return None
    client = await connect(account)
    try:
        if await client.is_user_authorized():
            await update_account_identity(account, client)
            account.status = AccountStatus.ACTIVE.value
        else:
            account.status = AccountStatus.DISCONNECTED.value
            account.monitoring = False
    except Exception:
        account.status = AccountStatus.ERROR.value
    return client


def shutdown_all():
    for account_id in list(_clients):
        try:
            asyncio.create_task(release_client(account_id))
        except RuntimeError:
            pass


def _login_api():
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise ValueError("TELEGRAM_API_ID / TELEGRAM_API_HASH not configured")
    return int(settings.telegram_api_id), settings.telegram_api_hash


async def _ensure_login(phone: str):
    client = _login_clients.get(phone)
    if client is None:
        api_id, api_hash = _login_api()
        client = TelegramClient(StringSession(), api_id, api_hash)
        _login_clients[phone] = client
        _login_states[phone] = LoginState()
    if not client.is_connected():
        await client.connect()
    return client


async def auth_send_code(phone: str):
    client = await _ensure_login(phone)
    for attempt in range(3):
        try:
            if not client.is_connected():
                await client.connect()
            sent = await client.send_code_request(phone)
            _login_states[phone].sent = {"phone_code_hash": getattr(sent, "phone_code_hash", None)}
            return
        except (RuntimeError, errors.AuthRestartError) as exc:
            if attempt == 2:
                raise
            logger.info("Restarting Telegram login connection: %s", exc)
            try:
                await client.disconnect()
            except Exception:
                pass
            api_id, api_hash = _login_api()
            client = TelegramClient(StringSession(), api_id, api_hash)
            _login_clients[phone] = client
            _login_states[phone] = LoginState()
            await asyncio.sleep(0.5)
            await client.connect()
    raise RuntimeError("Telegram authorization could not be restarted")


async def auth_confirm_code(phone: str, code: str):
    client = _login_clients.get(phone)
    if not client:
        raise ValueError("start authentication first")
    try:
        await client.sign_in(phone, code, phone_code_hash=_login_states[phone].sent.get("phone_code_hash"))
        return {"status": "ok"}
    except errors.SessionPasswordNeededError:
        _login_states[phone].needs_password = True
        return {"status": "twofa"}
    except errors.PhoneCodeInvalidError:
        return {"status": "invalid_code"}
    except errors.PhoneCodeExpiredError:
        return {"status": "code_expired"}


async def auth_confirm_password(phone: str, password: str):
    client = _login_clients.get(phone)
    if not client:
        raise ValueError("start authentication first")
    try:
        await client.sign_in(password=password)
        return True
    except errors.PasswordHashInvalidError:
        return False


async def finish_login(phone: str, account):
    login = _login_clients.pop(phone, None)
    _login_states.pop(phone, None)
    if not login:
        raise ValueError("no active login session")
    try:
        if not login.is_connected():
            await login.connect()
        if not await login.is_user_authorized():
            raise ValueError("Telegram session is not authorized")
        target = account.session_path or _session_path(account.id)
        # Save as SQLite session (not StringSession) so it persists across
        # restarts and can be shared between backend/worker processes.
        _save_session_as_sqlite(login, target)
        account.session_path = target
        await update_account_identity(account, login)
        _clients[account.id] = login
        return login
    except Exception:
        try:
            await login.disconnect()
        except Exception:
            pass
        raise


def _save_session_as_sqlite(client, target_path: str) -> None:
    """Save a TelegramClient's session state as an SQLite file.

    Telethon's default ``session.save()`` returns a StringSession string.
    We need an SQLite file so it can be shared between backend and worker
    processes via a Docker volume.
    """
    from telethon.sessions.sqlite import SQLiteSession as _SQLiteSession

    # Remove any old file so SQLiteSession creates a fresh database.
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(target_path + suffix)
        except FileNotFoundError:
            pass

    sqlite_sess = _SQLiteSession(target_path)
    # Copy state from the live StringSession session.
    src = client.session
    sqlite_sess._dc_id = src._dc_id
    sqlite_sess._server_address = src._server_address
    sqlite_sess._port = src._port
    sqlite_sess._auth_key = src._auth_key
    sqlite_sess._takeout_id = getattr(src, "_takeout_id", None)
    # Copy entities (may be dict or set depending on Telethon version).
    if hasattr(src, "_entities"):
        _ents = src._entities
        _iter = _ents if isinstance(_ents, (set, list)) else _ents.values()
        for entity in _iter:
            try:
                sqlite_sess.process_entities(entity)
            except Exception:
                pass
    # _update_session_table() must be called BEFORE save() because
    # save() only calls conn.commit() — it does NOT re-insert the
    # session row. Setting attributes on the Python object has no
    # effect on the DB until _update_session_table() writes them.
    sqlite_sess._update_session_table()
    sqlite_sess.save()
    sqlite_sess.close()
    logger.info("Saved session as SQLite: %s", target_path)
