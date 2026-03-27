from typing import Optional
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.db import get_session
from app.models import User
from app.auth_utils import verify_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    session: Session = Depends(get_session)
) -> User:
    """
    Dependency to retrieve the current authenticated user from a JWT token.
    """
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = payload.get("sub")
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme), 
    session: Session = Depends(get_session)
) -> Optional[User]:
    """
    Optional dependency to retrieve the current user if a valid token is provided.
    """
    if not token or token in ["undefined", "null", "none"] or "." not in token:
        return None
    try:
        payload = verify_token(token)
        if payload is None:
            return None
        user_id = payload.get("sub")
        return session.get(User, user_id)
    except Exception:
        return None

async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency to ensure the current authenticated user has admin privileges.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
