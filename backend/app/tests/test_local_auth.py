"""Phase 2 (Standalone Edition): local single-user auto-login + auth_mode reporting."""

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException, Request
from sqlmodel import Session, SQLModel, create_engine

from app.auth_utils import verify_token
from app.config import settings
from app.routers import auth as auth_router


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _request(host: str = "127.0.0.1") -> Request:
    """Minimal stand-in for a Starlette Request exposing request.client.host."""
    return cast(Request, SimpleNamespace(client=SimpleNamespace(host=host)))


def test_get_or_create_local_user_is_idempotent(session):
    u1 = auth_router.get_or_create_local_user(session)
    assert u1.id == auth_router.LOCAL_USER_ID
    assert u1.role == "admin"
    assert u1.hashed_password is None

    u2 = auth_router.get_or_create_local_user(session)
    assert u2.id == u1.id  # same row, not a duplicate


def test_local_login_standalone_loopback(session, monkeypatch):
    monkeypatch.setattr(settings, "APP_PROFILE", "standalone")
    resp = asyncio.run(auth_router.local_login(_request("127.0.0.1"), session=session))

    assert resp["token_type"] == "bearer"
    assert resp["user"]["id"] == auth_router.LOCAL_USER_ID
    assert resp["refresh_token"]
    payload = verify_token(resp["access_token"])
    assert payload is not None and payload["sub"] == auth_router.LOCAL_USER_ID


def test_local_login_hidden_in_server_profile(session, monkeypatch):
    monkeypatch.setattr(settings, "APP_PROFILE", "server")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth_router.local_login(_request("127.0.0.1"), session=session))
    assert exc.value.status_code == 404


def test_local_login_rejected_from_non_loopback(session, monkeypatch):
    monkeypatch.setattr(settings, "APP_PROFILE", "standalone")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth_router.local_login(_request("192.168.1.50"), session=session))
    assert exc.value.status_code == 403


def test_auth_mode_helper(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "a-client-id")
    assert settings.auth_mode() == "oauth"

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(settings, "APP_PROFILE", "standalone")
    assert settings.auth_mode() == "local"

    monkeypatch.setattr(settings, "APP_PROFILE", "server")
    assert settings.auth_mode() == "password"
