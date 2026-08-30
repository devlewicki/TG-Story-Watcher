from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

from telethon import TelegramClient, errors

from ..config import get_settings
from ..db import SessionLocal
from ..models import AccountStatus, TelegramAccount

logger = logging.getLogger("storywatcher.telegram")

settings = get_settings()

# Cached connected clients keyed by TelegramAccount.id
_clients: dict[int, TelegramClient] = {}

# Temporary login clients keyed by phone (multi-step auth). Telethon saves the
# session bits to disk when we call .save() after a successful sign-in.
_login_clients: dict[str, TelegramClient] = {}


@dataclass
class LoginState:
    sent: dict = field(default_factory=dict)
    needs_password: bool = False


_login_states: dict[str, LoginState] = {}


def _session_path(account_id: int) -> str:
    os.makedirs(settings.sessions_dir, exist_ok=True)
    return os.path.join(settings.sessions_dir, f"account_{account_id}.session")


def get_credentials(account: TelegramAccount) -> tuple[int, str]:
    api_id = account.api_id or settings.telegram_api_id
    api_hash = account.api_hash or settings.telegram_api_hash
    if not api_id or not api_hash:
        raise ValueError(
            "Telegram API ID/Hash not configured. Add to the account or set "
            "TELEGRAM_API_ID / TELEGRAM_API_HASH in the environment."
        )
    return int(api_id), api_hash


async def build_client(account: TelegramAccount) -> TelegramClient:
    api_id, api_hash = get_credentials(account)
    path = account.session_path or _session_path(account.id)
    return TelegramClient(path, api_id, api_hash)


async def get_client(account: TelegramAccount) -> TelegramClient:
    cached = _clients.get(account.id)
    if cached is not None:
        return cached
    client = await build_client(account)
    _clients[account.id] = client
    return client


async def connect(account: TelegramAccount) -> TelegramClient:
    client = await get_client(account)
    if not client.is_connected():
        await client.connect()
    return client


def drop_client(account_id: int) -> None:
    client = _clients.pop(account_id, None)
    if client is not None:
        try:
            asyncio.create_task(client.disconnect())
        except RuntimeError:
            pass


async def release_client(account_id: int) -> None:
    """Detach and fully disconnect the client, awaiting the shutdown so the
    SQLite session file is actually released (the worker process owns it)."""
    client = _clients.pop(account_id, None)
    if client is not None:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def update_account_identity(account: TelegramAccount, client: TelegramClient) -> None:
    me = await client.get_me()
    if me is None:
        return
    account.telegram_user_id = me.id if hasattr(me, "id") else 0
    account.username = getattr(me, "username", None)
    account.first_name = getattr(me, "first_name", None)
    account.last_name = getattr(me, "last_name", None)
    if getattr(me, "phone", None):
        account.phone = me.phone


async def start_account(account: TelegramAccount) -> TelegramClient:
    """Connect the account and refresh its authorization status."""
    client = await connect(account)
    try:
        if await client.is_user_authorized():
            await update_account_identity(account, client)
            account.status = AccountStatus.ACTIVE.value
        else:
            account.status = AccountStatus.AUTH_REQUIRED.value
    except Exception as exc:  # noqa: BLE001
        logger.warning("start_account(%s) failed: %s", account.id, exc)
        account.status = AccountStatus.ERROR.value
    return client


async def stop_account(client: TelegramClient) -> None:
    if client is not None:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def shutdown_all() -> None:
    for account_id, client in list(_clients.items()):
        try:
            asyncio.create_task(client.disconnect())
        except RuntimeError:
            pass
    _clients.clear()


# ---------------------------------------------------------------------------
# Multi-step login
# ---------------------------------------------------------------------------
def _login_api() -> tuple[int, str]:
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise ValueError("TELEGRAM_API_ID / TELEGRAM_API_HASH not configured")
    return int(settings.telegram_api_id), settings.telegram_api_hash


async def _ensure_login(phone: str) -> TelegramClient:
    client = _login_clients.get(phone)
    if client is None:
        api_id, api_hash = _login_api()
        client = TelegramClient(f"login_{phone}", api_id, api_hash)
        _login_clients[phone] = client
        _login_states[phone] = LoginState()
    if not client.is_connected():
        await client.connect()
    return client


async def auth_send_code(phone: str) -> None:
    client = await _ensure_login(phone)
    sent = await client.send_code_request(phone)
    _login_states[phone].sent = {
        "phone_code_hash": getattr(sent, "phone_code_hash", None),
        "phone_registered": getattr(sent, "phone_registered", None),
    }
    _login_states[phone].needs_password = False


async def auth_confirm_code(phone: str, code: str) -> dict:
    client = _login_clients.get(phone)
    if client is None:
        raise ValueError("start authentication first (send code)")
    state = _login_states[phone]
    phone_code_hash = (state.sent or {}).get("phone_code_hash")
    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        state.needs_password = False
        return {"status": "ok"}
    except errors.SessionPasswordNeededError:
        state.needs_password = True
        return {"status": "twofa"}
    except errors.PhoneCodeInvalidError:
        return {"status": "invalid_code"}
    except errors.PhoneCodeExpiredError:
        return {"status": "code_expired"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("auth_confirm_code failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def auth_confirm_password(phone: str, password: str) -> bool:
    client = _login_clients.get(phone)
    if client is None:
        raise ValueError("start authentication first (send code)")
    try:
        await client.sign_in(password=password)
        return True
    except errors.PasswordHashInvalidError:
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("auth_confirm_password failed: %s", exc)
        return False


async def finish_login(phone: str, account: TelegramAccount) -> TelegramClient:
    """After successful sign-in, bind the ephemeral login client to the account
    session file and register it in the managed map."""
    login_client = _login_clients.pop(phone, None)
    _login_states.pop(phone, None)
    if login_client is None:
        raise ValueError("no active login session for this phone")

    # Create a real session for the account, copy authorized data over.
    session_path = account.session_path or _session_path(account.id)
    api_id, api_hash = get_credentials(account)
    final = TelegramClient(session_path, api_id, api_hash)
    await final.connect()
    # Reuse the authorization from the ephemeral client.
    if login_client.session is not None and login_client.session.auth_key:
        final.session.auth_key = login_client.session.auth_key
        final.session.server_address = login_client.session.server_address
        final.session.port = login_client.session.port
        final.session.dc_id = login_client.session.dc_id
        if login_client.session.user_id:
            final.session.user_id = login_client.session.user_id
        account.session_path = session_path
    await final.save()
    _clients[account.id] = final
    try:
        await login_client.disconnect()
    except Exception:  # noqa: BLE001
        pass
    return final