"""Unit tests for auth_utils: JWT token creation."""
import pytest
from datetime import datetime, timedelta
from jose import jwt, JWTError

from services.auth_utils import create_access_token

_SECRET = "test-secret-key-for-tests"
_ALGORITHM = "HS256"


def test_create_access_token_returns_non_empty_string():
    token = create_access_token(42)
    assert isinstance(token, str)
    assert len(token) > 0


def test_token_subject_matches_user_id():
    token = create_access_token(99)
    payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    assert payload["sub"] == "99"


def test_token_expires_in_seven_days():
    token = create_access_token(1)
    payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    exp = datetime.utcfromtimestamp(payload["exp"])
    delta = exp - datetime.utcnow()
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, minutes=1)


def test_token_invalid_with_wrong_secret():
    token = create_access_token(1)
    with pytest.raises(JWTError):
        jwt.decode(token, "wrong-secret", algorithms=[_ALGORITHM])
