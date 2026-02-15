from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt
from passlib.context import CryptContext

from app.config import settings
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain text password against a hashed password.

    Args:
        plain_password: The password to check.
        hashed_password: The stored hash.

    Returns:
        True if the password matches, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """
    Hash a password string using bcrypt.

    Args:
        password: The plain text password.

    Returns:
        The hashed password string.
    """
    return pwd_context.hash(password)

def create_access_token(
    data: dict, 
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Payload data to encode.
        expires_delta: Optional expiration duration.

    Returns:
        Encoded JWT token as a string.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET, algorithm=settings.ALGORITHM
    )
    return encoded_jwt

def verify_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT token.

    Args:
        token: The JWT token string.

    Returns:
        The decoded payload as a dictionary, or None if invalid.
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.ALGORITHM]
        )
        return payload
    except (jwt.JWSError, jwt.JWTError):
        _logger.warning("Invalid or malformed JWT token provided")
        return None
    except Exception:
        _logger.exception("Unexpected error during JWT verification")
        return None
