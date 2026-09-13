"""FastAPI dependency that reads the session cookie off the request."""

from __future__ import annotations

from fastapi import Request

from app.core.config import get_settings


def get_session_token(request: Request) -> str | None:
    """The raw session token from the cookie, or None if absent."""
    return request.cookies.get(get_settings().auth_session_cookie_name)
