from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

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


def _read_session(path: str):
    if not os.path.isfile(path):
        return StringSession()
    with open(path, "rb") as file:
        raw = file.read()
    if raw.startswith(b"SQLite format 3"):
        return path
    try:
        return StringSession(raw.decode("utf-8").strip())
    except UnicodeDecodeError:
        return StringSession()


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
        durable_string = login.session.save()
        target = account.session_path or _session_path(account.id)
        tmp = f"{target}.tmp"
        with open(tmp, "w", encoding="utf-8") as file:
            file.write(durable_string)
        os.replace(tmp, target)
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
