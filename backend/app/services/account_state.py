"""Shared helpers for account state-transition diagnostics.

The account-death incidents (Sep 26 / Oct 01) went completely silent: the
worker changed ``status``/``monitoring`` and did not leave any trace in
``activity_logs``.  This module centralises the pieces every caller needs so a
transition can never vanish again:

* ``log_transition`` — one ``account_status`` activity event with the previous
  and new state, monitoring before/after, the responsible component and a
  safe reason (exception class + message, never secrets);
* ``classify_telegram_error`` — maps Telethon exceptions to a stable category
  so callers stop guessing AuthKeyDuplicated vs AuthKeyUnregistered by
  substring matching (the existing ``"authorization key" in str(exc)`` check
  matched BOTH messages and wrongly deleted a valid session file on
  ``AuthKeyUnregisteredError``);
* a small per-account in-process backoff for *transient* RPC failures so the
  worker does not hammer ``GetState``/``GetUsers`` every second while Telegram
  is flaky, while still allowing a bounded automatic retry.

Nothing here may raise or log secrets.  Messages are plain diagnostic text.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger("storywatcher.account_state")

# Stable error categories written into ``account_status`` events.
AUTH_DUPLICATED = "auth_key_duplicated"
AUTH_UNREGISTERED = "auth_key_unregistered"
UNAUTHORIZED = "session_not_authorized"
TRANSIENT_RPC = "transient_rpc_error"
FLOOD_WAIT = "flood_wait"
NETWORK = "network_error"
DB_LOCKED = "database_locked"
UNKNOWN = "unknown_error"

# Components that may change account state (source field).
SOURCE_WORKER = "worker"
SOURCE_SCHEDULER = "scheduler"
SOURCE_DISCOVERY = "discovery"
SOURCE_CLIENT_MANAGER = "client_manager"
SOURCE_API = "api"
SOURCE_AUTH = "auth"

# How long a transient auth-check failure puts an account on a local retry
# backoff before the worker attempts a fresh check.
TRANSIENT_BACKOFF_SECONDS = 60.0

_SAFE_REASON_MAX = 500


def _safe_reason(exc: BaseException | None, prefix: str = "") -> str:
    """Human-readable, secret-safe reason for a transition."""
    if exc is None:
        return prefix or "no exception"
    parts = [f"{type(exc).__name__}"]
    try:
        text = str(exc).strip()
    except Exception:  # noqa: BLE001
        text = ""
    if text and text not in ("()", "None"):
        parts.append(str(text)[:_SAFE_REASON_MAX])
    if prefix:
        text = f"{prefix}: {'; '.join(parts)}"
    else:
        text = "; ".join(parts)
    return text[:_SAFE_REASON_MAX + 200]


def classify_telegram_error(exc: BaseException) -> tuple[str, bool]:
    """Map a raised exception to a (category, drop_session) tuple.

    ``drop_session`` is True only when Telegram invalidated the auth key itself
    (``AuthKeyDuplicatedError``) — the session file must be discarded so the
    re-login flow starts from a clean slate.  A revoked/terminated session
    (``AuthKeyUnregisteredError``/``UnauthorizedError``) keeps the file so the
    login flow can reuse it (current behaviour in ``scheduler.py``).
    """
    err_str = str(exc).lower()
    message = getattr(exc, "message", None) or getattr(exc, "error_message", None) or err_str

    try:
        import sqlite3
        if isinstance(exc, sqlite3.OperationalError) and "database is locked" in message:
            return DB_LOCKED, False
    except Exception:  # noqa: BLE001
        pass
    if "database is locked" in message:
        return DB_LOCKED, False

    try:
        from telethon import errors
    except Exception:  # noqa: BLE001
        errors = None  # type: ignore[assignment]

    if errors is not None:
        # Order matters: these are all subclasses of RPCError.
        if isinstance(exc, errors.AuthKeyDuplicatedError):
            return AUTH_DUPLICATED, True
        if isinstance(exc, (errors.AuthKeyUnregisteredError, errors.UnauthorizedError)):
            return AUTH_UNREGISTERED, False
        if isinstance(exc, errors.FloodWaitError):
            return FLOOD_WAIT, False

    # Message fallback, deliberately OUTSIDE the telethon-instance guards: the
    # historical bug glued the outcome to a substring ("authorization key") that
    # appears in BOTH the duplicated and the unregistered string.  Keep the
    # string matching narrow, auth-marker only, and always decide the session-
    # file fate from it (drop ONLY for a duplicated key).
    low = message.lower()
    if "duplicated" in low and "authorization key" in low:
        return AUTH_DUPLICATED, True
    if "key" in low and ("not registered" in low or "invalid" in low):
        return AUTH_UNREGISTERED, False
    if "authorization key" in low:
        return AUTH_UNREGISTERED, False

    if errors is not None:
        # Any other RPC error is a transient/account-neutral failure: no state
        # change, no session drop — the worker retries on the bounded backoff.
        if isinstance(exc, errors.RPCError):
            return TRANSIENT_RPC, False

    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return NETWORK, False
    return UNKNOWN, False


def log_transition(
    *,
    account_id: int,
    prev_status: str | None,
    new_status: str | None,
    prev_monitoring: bool | None,
    new_monitoring: bool | None,
    source: str,
    reason: str,
    exc: BaseException | None = None,
    operation_id: str | None = None,
    db=None,
) -> None:
    """Persist one ``account_status`` activity event.

    ``db`` may be an open session (the caller's committed transaction) or None
    (a short-lived session is created).  Never raises.
    """
    metadata: dict[str, Any] = {
        "previous_status": prev_status,
        "new_status": new_status,
        "previous_monitoring": prev_monitoring,
        "new_monitoring": new_monitoring,
        "source": source,
        "reason": reason,
        "exception_type": type(exc).__name__ if exc is not None else None,
        "message": _safe_reason(exc) if exc is not None else None,
    }
    if operation_id is not None:
        metadata["operation_id"] = operation_id

    from ..services import activity

    activity.log(
        f"account {account_id} status: "
        f"{prev_status or '?'}/{prev_monitoring!r} -> {new_status or '?'}/{new_monitoring!r} "
        f"[{source}] {reason}",
        event_type="account_status",
        level="WARNING" if new_status not in (None, "ACTIVE") else "INFO",
        account_id=account_id,
        metadata=metadata,
        db=db,
    )


def log_transition_if_changed(
    *,
    account_id: int,
    prev_status: str | None,
    new_status: str | None,
    prev_monitoring: bool | None,
    new_monitoring: bool | None,
    source: str,
    reason: str,
    exc: BaseException | None = None,
    operation_id: str | None = None,
    db=None,
) -> None:
    """Like :func:`log_transition` but skips events that change nothing.

    Avoids churn (every sweep would otherwise write an identical
    ``account_status`` row for active accounts).
    """
    if prev_status == new_status and prev_monitoring == new_monitoring:
        return
    log_transition(
        account_id=account_id,
        prev_status=prev_status,
        new_status=new_status,
        prev_monitoring=prev_monitoring,
        new_monitoring=new_monitoring,
        source=source,
        reason=reason,
        exc=exc,
        operation_id=operation_id,
        db=db,
    )


# ---------------------------------------------------------------------------
# Per-account in-process backoff for transient failures.
# ---------------------------------------------------------------------------
_transient_since: dict[int, float] = {}


def mark_transient(account_id: int, backoff_s: float = TRANSIENT_BACKOFF_SECONDS) -> None:
    _transient_since[account_id] = time.monotonic() + backoff_s


def in_transient_backoff(account_id: int) -> bool:
    until = _transient_since.get(account_id, 0.0)
    return time.monotonic() < until


def clear_transient(account_id: int) -> None:
    _transient_since.pop(account_id, None)


def reset_for_tests() -> None:
    _transient_since.clear()


# Default per-request timeout for an authorization probe.
DEFAULT_AUTH_CHECK_TIMEOUT = 30.0


async def check_authorization(client, account_id: int, timeout: float = DEFAULT_AUTH_CHECK_TIMEOUT) -> str:
    """Probe whether ``client`` is authorized, distinguishing transient RPC/network
    failures from a confirmed session loss.

    Returns ``authorized`` / ``unauthorized`` / ``transient``.

    ``client.is_user_authorized()`` swallows every RPC error and returns False,
    which is what turned a temporary Telegram hiccup into a DISCONNECTED +
    monitoring=False state (the Sep 26 incident).  Here we issue the request
    directly and classify exceptions: only a definitive session revocation
    counts as ``unauthorized``; anything reachability-flavoured goes to
    ``transient`` and is retried on a bounded per-account backoff instead of
    killing the account.
    """
    if not client.has_authorization():
        # Session has no auth key at all -> nothing to fall back on.
        return "unauthorized"
    if in_transient_backoff(account_id):
        return "transient"
    from telethon import functions
    from telethon import types as _tl_types

    try:
        result = await asyncio.wait_for(
            client(functions.users.GetUsersRequest([_tl_types.InputUserSelf()])),
            timeout=timeout,
        )
    except (asyncio.TimeoutError, ConnectionError, TimeoutError, OSError):
        mark_transient(account_id)
        return "transient"
    except Exception as exc:  # noqa: BLE001
        category, _drop = classify_telegram_error(exc)
        if category in (AUTH_DUPLICATED, AUTH_UNREGISTERED, UNAUTHORIZED):
            return "unauthorized"
        mark_transient(account_id)
        return "transient"
    user = result[0] if isinstance(result, (list, tuple)) and result else None
    if isinstance(user, _tl_types.User):
        return "authorized"
    return "unauthorized"