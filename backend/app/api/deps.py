from __future__ import annotations
from fastapi import Header, HTTPException, status
from ..multitenancy import user_id_from_token

def current_user_id(x_api_token: str | None = Header(default=None)) -> int:
    user_id = user_id_from_token(x_api_token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход пользователя")
    return user_id

def require_api_token(x_api_token: str | None = Header(default=None)) -> None:
    if user_id_from_token(x_api_token) is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход пользователя")
