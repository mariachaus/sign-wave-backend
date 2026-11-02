from jose import jwt, JWTError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from services.auth_utils import SECRET_KEY, ALGORITHM
from db.connection import get_db
from db.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="No token")

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")


def get_verified_user_id(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Same as get_current_user_id, but only for users who confirmed their email."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not user.is_email_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    return user_id
