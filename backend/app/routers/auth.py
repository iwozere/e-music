import uuid
import httpx
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, Form
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select, or_
from jose import jwt as jose_jwt
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from app.models import User
from app.config import settings
from app.db import get_session
from app.auth_utils import create_access_token, get_password_hash, verify_password
from app.dependencies import get_current_user
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=User)
async def register(
    username: str, 
    email: str, 
    password: str, 
    session: Session = Depends(get_session)
) -> User:
    """
    Register a new user with username and password.
    """
    # Check if user exists
    _logger.info("Registering new user: %s", username)
    statement = select(User).where(or_(User.username == username, User.email == email))
    existing = session.exec(statement).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        email=email,
        hashed_password=get_password_hash(password),
        role="admin" if session.exec(select(User)).first() is None else "user"
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

@router.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    session: Session = Depends(get_session)
) -> dict:
    """
    OAuth2 compatible token login, retrieve an access token for future requests.
    """
    _logger.info("Token login attempt for: %s", form_data.username)
    statement = select(User).where(User.username == form_data.username)
    user = session.exec(statement).first()
    if not user or not user.hashed_password or not verify_password(form_data.password, user.hashed_password):
        _logger.warning("Failed login attempt for: %s", form_data.username)
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    access_token = create_access_token(
        data={"sub": user.id, "email": user.email, "role": user.role}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=User)
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
async def auth_callback(code: str, session: Session = Depends(get_session)) -> dict:
    """
    Handle the Google OAuth2 callback.
    """
    _logger.info("Handling Google OAuth2 callback")
    # Exchange code for token
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
        
        # fallback for mobile/Android codes
        if "error" in token_data:
            _logger.info("Retrying Google token exchange without redirect_uri...")
            payload.pop("redirect_uri", None)
            token_response = await client.post("https://oauth2.googleapis.com/token", data=payload)
            token_data = token_response.json()

        if "error" in token_data:
            _logger.error("Google Auth error: %s", token_data.get("error_description"))
            raise HTTPException(status_code=400, detail=token_data.get("error_description"))
        
        id_token_str = token_data.get("id_token")
        
        # Security: Properly verify the ID token signature and audience
        try:
            idinfo = google_id_token.verify_oauth2_token(id_token_str, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
            email = idinfo["email"]
            google_id = idinfo["sub"]
        except Exception as e:
            _logger.error("Failed to verify Google ID token: %s", str(e))
            raise HTTPException(status_code=401, detail="Invalid Google token")
        
        # Check if user exists
        statement = select(User).where(User.email == email)
        user = session.exec(statement).first()
        
        if not user:
            _logger.info("Creating new Google user: %s", email)
            user = User(
                id=google_id,
                username=email.split("@")[0],
                email=email,
                role="admin" if session.exec(select(User)).first() is None else "user"
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            
        access_token = create_access_token(
            data={"sub": user.id, "email": user.email, "role": user.role}
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role
            }
        }

@router.post("/google")
async def google_auth(token_data: dict, session: Session = Depends(get_session)) -> dict:
    """
    Handle Google Auth via ID Token (Web GSI or Mobile).
    """
    token = token_data.get("id_token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing id_token")
    
    try:
        # Verify the ID token
        idinfo = google_id_token.verify_oauth2_token(token, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
        
        email = idinfo["email"]
        google_id = idinfo["sub"]
        
        # Check if user exists
        statement = select(User).where(User.email == email)
        user = session.exec(statement).first()
        
        if not user:
            _logger.info("Creating new Google user: %s", email)
            user = User(
                id=google_id,
                username=email.split("@")[0],
                email=email,
                role="admin" if session.exec(select(User)).first() is None else "user"
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            
        access_token = create_access_token(
            data={"sub": user.id, "email": user.email, "role": user.role}
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role
            }
        }
    except ValueError as e:
        _logger.error("Invalid Google Token: %s", str(e))
        raise HTTPException(status_code=401, detail="Invalid Google token")

@router.post("/google/login")
async def google_login_redirect(
    request: Request, 
    credential: str = Form(...), 
    session: Session = Depends(get_session)
) -> Any:
    """
    Handle Google GSI redirect mode POST.
    """
    try:
        # Verify the ID token (credential)
        idinfo = google_id_token.verify_oauth2_token(credential, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
        
        email = idinfo["email"]
        google_id = idinfo["sub"]
        
        # Check if user exists
        statement = select(User).where(User.email == email)
        user = session.exec(statement).first()
        
        if not user:
            _logger.info("Creating new Google user from redirect: %s", email)
            user = User(
                id=google_id,
                username=email.split("@")[0],
                email=email,
                role="admin" if session.exec(select(User)).first() is None else "user"
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            
        access_token = create_access_token(
            data={"sub": user.id, "email": user.email, "role": user.role}
        )
        
        # Redirect back to the frontend
        referer = request.headers.get("referer")
        if referer and ("localhost" in referer or "127.0.0.1" in referer):
            from urllib.parse import urlparse
            p = urlparse(referer)
            base_url = f"{p.scheme}://{p.netloc}"
        else:
            base_url = f"https://{settings.DOMAIN}"
            
        frontend_url = f"{base_url}/#token={access_token}"
        _logger.info("Redirecting back to: %s", base_url)
        return RedirectResponse(url=frontend_url, status_code=303)
        
    except ValueError as e:
        _logger.error("Invalid Google Token in redirect: %s", str(e))
        raise HTTPException(status_code=401, detail="Invalid Google token")

@router.get("/config")
async def get_auth_config(request: Request) -> dict:
    """
    Expose public configuration for the frontend auth.
    """
    return {
        "google_client_id": settings.GOOGLE_CLIENT_ID,
        "api_base_url": str(request.base_url).rstrip('/')
    }
