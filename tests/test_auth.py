"""HTTP contract tests for auth routes that do not require PostgreSQL."""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_pool
from app.auth import service
from app.auth.entities import IssuedSession, User
from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
async def auth_client() -> AsyncIterator[tuple[AsyncClient, object, Settings]]:
    pool = object()
    settings = Settings(auth_session_cookie_name="test_session", auth_session_ttl_days=2)
    app: FastAPI = create_app()
    app.dependency_overrides[get_pool] = lambda: pool
    app.dependency_overrides[get_settings] = lambda: settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, pool, settings


async def test_register_returns_user_and_sets_configured_session_cookie(
    auth_client: tuple[AsyncClient, object, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, expected_pool, _ = auth_client
    user = User(id=7, name="Ada Lovelace", email="ada@example.com")

    async def register(pool: object, **credentials: str) -> User:
        assert pool is expected_pool
        assert credentials == {
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "password": "correct horse",
        }
        return user

    async def create_session(pool: object, *, user_id: int, ttl: dt.timedelta) -> IssuedSession:
        assert pool is expected_pool
        assert user_id == user.id
        assert ttl == dt.timedelta(days=2)
        return IssuedSession(
            token="browser-token",
            expires_at=dt.datetime(2026, 9, 14, tzinfo=dt.UTC),
        )

    monkeypatch.setattr(service, "register", register)
    monkeypatch.setattr(service, "create_session", create_session)

    response = await client.post(
        "/api/v1/auth/register",
        json={"name": user.name, "email": user.email, "password": "correct horse"},
    )

    assert response.status_code == 201
    assert response.json() == {"user": {"id": 7, "name": user.name, "email": user.email}}
    cookie = response.headers["set-cookie"]
    assert "test_session=browser-token" in cookie
    assert "HttpOnly" in cookie
    assert "Max-Age=172800" in cookie
    assert "SameSite=lax" in cookie


async def test_me_reads_the_configured_cookie_and_returns_a_public_user(
    auth_client: tuple[AsyncClient, object, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, expected_pool, _ = auth_client

    async def get_current_user(pool: object, *, session_token: str | None) -> User:
        assert pool is expected_pool
        assert session_token == "existing-token"
        return User(id=9, name="Grace Hopper", email="grace@example.com")

    monkeypatch.setattr(service, "get_current_user", get_current_user)
    client.cookies.set("test_session", "existing-token")

    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": 9,
        "name": "Grace Hopper",
        "email": "grace@example.com",
    }


async def test_logout_revokes_and_deletes_the_configured_cookie(
    auth_client: tuple[AsyncClient, object, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, expected_pool, _ = auth_client
    received: dict[str, Any] = {}

    async def logout(pool: object, *, session_token: str | None) -> None:
        received.update(pool=pool, session_token=session_token)

    monkeypatch.setattr(service, "logout", logout)
    client.cookies.set("test_session", "existing-token")

    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert received == {"pool": expected_pool, "session_token": "existing-token"}
    assert "test_session=\"\"" in response.headers["set-cookie"]
