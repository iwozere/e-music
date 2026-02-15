import pytest
from app.auth_utils import get_password_hash, verify_password

def test_password_hashing() -> None:
    """
    Test that password hashing and verification works correctly.
    """
    password = "secret_password"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False

def test_token_creation() -> None:
    """
    Test token creation (logic only, requires settings mock or env).
    """
    from datetime import timedelta
    from app.auth_utils import create_access_token
    
    token = create_access_token(
        data={"sub": "test_user"}, 
        expires_delta=timedelta(minutes=10)
    )
    assert isinstance(token, str)
    assert len(token) > 0
