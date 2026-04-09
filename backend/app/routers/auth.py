import uuid
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlmodel import Session, or_, select

from app.auth_utils import (
    get_password_hash,
    issue_access_and_refresh,
    revoke_refresh_token,
    verify_password,
    validate_refresh_token,
)
from app.config import settings
from app.db import get_session
from app.dependencies import get_current_user
from app.limiter_ext import limiter
from app.models import User
from app.schemas import (
    GoogleAuthBody,
    LogoutBody,
    RefreshBody,
    RegisterBody,
    TokenPairResponse,
    UserPublic,
)
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _role_for_email(email: str) -> str:
    e = email.strip().lower()
    if e in settings.admin_email_set():
        return "admin"
    return "user"


def _sync_role(session: Session, user: User) -> None:
    desired = _role_for_email(user.email)
    if user.role != desired:
        user.role = desired
        session.add(user)


@router.post("/register", response_model=UserPublic)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: RegisterBody,
    session: Session = Depends(get_session),
) -> Any:
    """
    Register a new user with username and password (JSON body).
    """
    _logger.info("Registering new user: %s", body.username)
    statement = select(User).where(
        or_(User.username == body.username, User.email == str(body.email))
    )
    existing = session.exec(statement).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    user = User(
        id=str(uuid.uuid4()),
        username=body.username,
        email=str(body.email),
        hashed_password=get_password_hash(body.password),
        role=_role_for_email(str(body.email)),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/token")
@limiter.limit("15/minute")
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
) -> dict:
    """
    OAuth2 compatible token login; returns access and refresh tokens.
    """
    _logger.info("Token login attempt for: %s", form_data.username)
    statement = select(User).where(User.username == form_data.username)
    user = session.exec(statement).first()
    if not user or not user.hashed_password or not verify_password(
        form_data.password, user.hashed_password
    ):
        _logger.warning("Failed login attempt for: %s", form_data.username)
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    _sync_role(session, user)
    session.commit()
    session.refresh(user)

    access_token, refresh_token, expires_in = issue_access_and_refresh(session, user)
    session.commit()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


@router.post("/refresh", response_model=TokenPairResponse)
@limiter.limit("30/minute")
async def refresh_tokens(
    request: Request,
    body: RefreshBody,
    session: Session = Depends(get_session),
) -> dict:
    """
    Exchange a refresh token for a new access + refresh pair (rotation).
    """
    pair = validate_refresh_token(session, body.refresh_token)
    if not pair:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    user, row = pair
    session.delete(row)
    _sync_role(session, user)
    session.commit()
    session.refresh(user)

    access_token, refresh_token, expires_in = issue_access_and_refresh(session, user)
    session.commit()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


@router.post("/logout")
async def logout(
    body: LogoutBody,
    session: Session = Depends(get_session),
) -> dict:
    """
    Revoke a refresh token (no-op if missing or unknown).
    """
    if body.refresh_token:
        revoke_refresh_token(session, body.refresh_token)
        session.commit()
    return {"status": "ok"}


@router.get("/me", response_model=UserPublic)
async def read_users_me(current_user: User = Depends(get_current_user)) -> User:
    """
    Get current user's profile information.
    """
    return current_user


@router.get("/login")
async def login() -> dict:
    """
    Get the Google OAuth2 authorization URL.
    """
    google_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={settings.GOOGLE_CLIENT_ID}&"
        f"redirect_uri={settings.GOOGLE_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope=openid%20email%20profile"
    )
    return {"url": google_url}


@router.get("/callback")
@limiter.limit("30/minute")
async def auth_callback(
    request: Request,
    code: str,
    session: Session = Depends(get_session),
) -> dict:
    """
    Handle the Google OAuth2 callback.
    """
    _logger.info("Handling Google OAuth2 callback")
    async with httpx.AsyncClient() as client:
        payload = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }

        token_response = await client.post("https://oauth2.googleapis.com/token", data=payload)
        token_data = token_response.json()

        if "error" in token_data:
            _logger.info("Retrying Google token exchange without redirect_uri...")
            payload.pop("redirect_uri", None)
            token_response = await client.post("https://oauth2.googleapis.com/token", data=payload)
            token_data = token_response.json()

        if "error" in token_data:
            _logger.error("Google Auth error: %s", token_data.get("error_description"))
            raise HTTPException(status_code=400, detail=token_data.get("error_description"))

        id_token_str = token_data.get("id_token")
        if not id_token_str:
            raise HTTPException(status_code=400, detail="Missing id_token in token response")

        try:
            idinfo = google_id_token.verify_oauth2_token(
                str(id_token_str), google_requests.Request(), settings.GOOGLE_CLIENT_ID
            )
            email = idinfo["email"]
            google_id = idinfo["sub"]
        except Exception as e:
            _logger.error("Failed to verify Google ID token: %s", str(e))
            raise HTTPException(status_code=401, detail="Invalid Google token")

        statement = select(User).where(User.email == email)
        user = session.exec(statement).first()

        if not user:
            _logger.info("Creating new Google user: %s", email)
            user = User(
                id=google_id,
                username=email.split("@")[0],
                email=email,
                role=_role_for_email(email),
            )
            session.add(user)
            session.commit()
            session.refresh(user)
        else:
            _sync_role(session, user)
            session.commit()
            session.refresh(user)

        access_token, refresh_token, expires_in = issue_access_and_refresh(session, user)
        session.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
            },
        }


@router.post("/google")
@limiter.limit("30/minute")
async def google_auth(
    request: Request,
    body: GoogleAuthBody,
    session: Session = Depends(get_session),
) -> dict:
    """
    Handle Google Auth via ID Token (Web GSI or Mobile).
    """
    try:
        idinfo = google_id_token.verify_oauth2_token(
            body.id_token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )

        email = idinfo["email"]
        google_id = idinfo["sub"]

        statement = select(User).where(User.email == email)
        user = session.exec(statement).first()

        if not user:
            _logger.info("Creating new Google user: %s", email)
            user = User(
                id=google_id,
                username=email.split("@")[0],
                email=email,
                role=_role_for_email(email),
            )
            session.add(user)
            session.commit()
            session.refresh(user)
        else:
            _sync_role(session, user)
            session.commit()
            session.refresh(user)

        access_token, refresh_token, expires_in = issue_access_and_refresh(session, user)
        session.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
            },
        }
    except ValueError as e:
        _logger.error("Invalid Google Token: %s", str(e))
        raise HTTPException(status_code=401, detail="Invalid Google token")


@router.post("/google/login")
@limiter.limit("30/minute")
async def google_login_redirect(
    request: Request,
    credential: str = Form(...),
    session: Session = Depends(get_session),
) -> Any:
    """
    Handle Google GSI redirect mode POST.
    """
    try:
        idinfo = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )

        email = idinfo["email"]
        google_id = idinfo["sub"]

        statement = select(User).where(User.email == email)
        user = session.exec(statement).first()

        if not user:
            _logger.info("Creating new Google user from redirect: %s", email)
            user = User(
                id=google_id,
                username=email.split("@")[0],
                email=email,
                role=_role_for_email(email),
            )
            session.add(user)
            session.commit()
            session.refresh(user)
        else:
            _sync_role(session, user)
            session.commit()
            session.refresh(user)

        access_token, refresh_token, _expires_in = issue_access_and_refresh(session, user)
        session.commit()

        base_url = str(request.base_url).rstrip("/")
        if "localhost" not in base_url and "127.0.0.1" not in base_url:
            base_url = f"https://{settings.DOMAIN}"

        frontend_url = (
            f"{base_url}/#access_token={quote(access_token, safe='')}"
            f"&refresh_token={quote(refresh_token, safe='')}"
        )
        _logger.info("Redirecting back to: %s", base_url)
        return RedirectResponse(url=frontend_url, status_code=303)

    except ValueError as e:
        _logger.error("Invalid Google Token in redirect: %s", str(e))
        raise HTTPException(status_code=401, detail="Invalid Google token")
