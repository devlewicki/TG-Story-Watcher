from __future__ import annotations

"""
API authentication for the web panel.

The whole web panel is protected by a single API token configured via
``STORYWATCHER_API_TOKEN`` (or ``API_TOKEN`` for short) in the environment /
``.env``. The frontend sends it in the ``X-API-Token`` header.
"""
import secrets

from fastapi import Header, HTTPException, status

from ..config import get_settings

_settings = get_settings()


def _expected_token() -> str | None:
    token = _settings.api_token
    if not token and not _settings.debug:
        # In debug mode an unset token is tolerated so the panel is usable
        # straight out of the box during development.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API token not configured. Set STORYWATCHER_API_TOKEN in .env",
        )
    return token if token else None


def require_api_token(x_api_token: str | None = Header(default=None)) -> None:
    expected = _expected_token()
    if expected is None:
        # debug mode with no token configured -> allow
        return
    if not x_api_token or not secrets.compare_digest(x_api_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
        )