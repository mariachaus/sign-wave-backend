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
    db: Session = Depends(get_db),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="No token")

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
        # tokens issued before token_version existed have no "ver" claim and count as version 0
        version = int(payload.get("ver", 0))
    except (JWTError, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.get(User, user_id)
    if not user or user.token_version != version:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user_id


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
