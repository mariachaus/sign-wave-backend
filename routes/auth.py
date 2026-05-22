import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import requests as http_requests

from werkzeug.security import generate_password_hash, check_password_hash

from db.connection import get_db
from db.models import User, UserSetting, UserStreak, UserAchievement, Achievement, PasswordResetToken
from services.email_service import send_password_reset

from services.auth_utils import create_access_token
from schemas import RegisterRequest, LoginRequest, GoogleLoginRequest, ForgotPasswordRequest, ResetPasswordRequest

GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_RESET_TOKEN_TTL_HOURS = 1

router = APIRouter(tags=["Auth"])


# ---------------- REGISTER ----------------

@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):

    username = data.username
    email = data.email
    password = data.password

    # 1. Check if user exists
    existing_user = db.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="User with this username or email already exists"
        )

    try:
        # 3. Hash password
        hashed_pw = generate_password_hash(password)

        # 4. Create user
        new_user = User(
            username=username,
            email=email,
            password_hash=hashed_pw,
            total_xp=0
        )

        db.add(new_user)
        db.flush()  # get ID

        # 5. Default relations
        db.add(UserSetting(user_id=new_user.id))
        db.add(UserStreak(user_id=new_user.id))

        # 6. Achievement logic
        welcome_ach = db.query(Achievement).filter_by(title="First Wave").first()

        if welcome_ach:
            db.add(UserAchievement(
                user_id=new_user.id,
                achievement_id=welcome_ach.id
            ))

            # type ignore — це нормально для SQLAlchemy + IDE
            new_user.total_xp = (new_user.total_xp or 0) + welcome_ach.points_awarded  # type: ignore

        db.commit()

        return {
            "message": "Registration successful. 'First Wave' achievement granted."
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ---------------- LOGIN ----------------

@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):

    username = data.username
    password = data.password

    user = db.query(User).filter(User.username == username).first()

    if not user or not check_password_hash(str(user.password_hash), password):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    # тимчасовий токен (без external libs)
    access_token = create_access_token(user.id) # type: ignore

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username,
        "user_id": user.id
    }


# ---------------- GOOGLE LOGIN ----------------

@router.post("/google")
def google_login(data: GoogleLoginRequest, db: Session = Depends(get_db)):
    access_token = data.access_token

    # Get user info from Google
    resp = http_requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"}
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    info = resp.json()
    google_id = info.get("sub")
    email = info.get("email")
    name = info.get("name") or email.split("@")[0]
    avatar_url = info.get("picture")

    if not google_id or not email:
        raise HTTPException(status_code=400, detail="Google account missing required fields")

    # Find or create user
    user = db.query(User).filter(User.google_id == google_id).first()

    if not user:
        # Check if email already exists (regular account)
        user = db.query(User).filter(User.email == email).first()
        if user:
            # Link Google ID to existing account
            user.google_id = google_id  # type: ignore
            if not user.avatar_url:
                user.avatar_url = avatar_url  # type: ignore
        else:
            # Create new user
            username = name.replace(" ", "_").lower()
            # Ensure unique username
            base = username
            counter = 1
            while db.query(User).filter(User.username == username).first():
                username = f"{base}{counter}"
                counter += 1

            user = User(
                username=username,
                email=email,
                google_id=google_id,
                avatar_url=avatar_url,
                total_xp=0
            )
            db.add(user)
            db.flush()

            db.add(UserSetting(user_id=user.id))
            db.add(UserStreak(user_id=user.id))

            welcome_ach = db.query(Achievement).filter_by(title="First Wave").first()
            if welcome_ach:
                db.add(UserAchievement(user_id=user.id, achievement_id=welcome_ach.id))
                user.total_xp = (user.total_xp or 0) + welcome_ach.points_awarded  # type: ignore

        db.commit()
        db.refresh(user)

    access_token = create_access_token(user.id)  # type: ignore
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username,
        "user_id": user.id
    }


# ---------------- FORGOT PASSWORD ----------------

_SAFE_RESPONSE = {"message": "If this email is registered, you will receive a reset link."}

@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    # Return same response regardless — avoids email enumeration
    if not user or not user.password_hash:
        return _SAFE_RESPONSE

    # Replace any existing token for this user
    db.query(PasswordResetToken).filter_by(user_id=user.id).delete()

    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=_RESET_TOKEN_TTL_HOURS)
    db.add(PasswordResetToken(user_id=user.id, token=token, expires_at=expires_at))
    db.commit()

    lang = user.settings.language if user.settings else "uk"
    try:
        send_password_reset(user.email, user.username, token, lang=lang)
    except Exception as e:
        # Don't expose email errors to the client
        import logging
        logging.getLogger("signwave").error(f"password reset email failed for {user.email}: {e}")

    return _SAFE_RESPONSE


# ---------------- RESET PASSWORD ----------------

@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    reset_token = db.query(PasswordResetToken).filter_by(token=data.token).first()

    if not reset_token or reset_token.expires_at < datetime.utcnow():
        if reset_token:
            db.delete(reset_token)
            db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = db.query(User).filter_by(id=reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.password_hash = generate_password_hash(data.new_password)  # type: ignore
    db.delete(reset_token)
    db.commit()

    return {"message": "Password updated successfully"}