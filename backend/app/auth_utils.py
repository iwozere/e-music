import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from jose import jwt
from passlib.context import CryptContext
from sqlmodel import Session, select

from app.config import settings
from app.models import RefreshToken, User
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


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(f"{raw}:{settings.JWT_SECRET}".encode()).hexdigest()


def create_refresh_token_raw() -> str:
    return secrets.token_urlsafe(48)


def save_refresh_token(session: Session, user_id: str, raw: str) -> None:
    expires = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    row = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user_id,
        token_hash=hash_refresh_token(raw),
        expires_at=expires,
    )
    session.add(row)


def validate_refresh_token(
    session: Session, raw: str
) -> Optional[Tuple[User, RefreshToken]]:
    th = hash_refresh_token(raw)
    row = session.exec(select(RefreshToken).where(RefreshToken.token_hash == th)).first()
    if not row or row.expires_at < datetime.now(timezone.utc):
        return None
    user = session.get(User, row.user_id)
    if not user:
        return None
    return user, row


def revoke_refresh_token(session: Session, raw: str) -> None:
    th = hash_refresh_token(raw)
    row = session.exec(select(RefreshToken).where(RefreshToken.token_hash == th)).first()
    if row:
        session.delete(row)


def sign_stream_url(track_id: str, exp: int, user_id: str) -> str:
    msg = f"{track_id}\n{exp}\n{user_id}".encode()
    return hmac.new(
        settings.stream_signing_secret().encode(),
        msg,
        hashlib.sha256,
    ).hexdigest()


def verify_stream_params(track_id: str, exp: int, user_id: str, sig: str) -> bool:
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(datetime.now(timezone.utc).timestamp()):
        return False
    expected = sign_stream_url(track_id, exp_i, user_id)
    try:
        return hmac.compare_digest(expected, sig)
    except TypeError:
        return False


def issue_access_and_refresh(session: Session, user: User) -> tuple[str, str, int]:
    access = create_access_token(
        data={"sub": user.id, "email": user.email, "role": user.role}
    )
    raw = create_refresh_token_raw()
    save_refresh_token(session, user.id, raw)
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return access, raw, expires_in
