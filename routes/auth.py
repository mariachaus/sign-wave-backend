import secrets
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import requests as http_requests

from werkzeug.security import generate_password_hash, check_password_hash

from db.connection import get_db
from db.models import (
    User, UserSetting, UserStreak, UserAchievement, Achievement,
    PasswordResetToken, EmailVerificationToken,
)
from services.email_service import send_password_reset, send_email_verification
from services import rate_limiter

from core.dependencies import get_current_user_id
from services.auth_utils import create_access_token
from schemas import (
    RegisterRequest, LoginRequest, GoogleLoginRequest, ForgotPasswordRequest,
    ResetPasswordRequest, VerifyEmailRequest,
)

GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_RESET_TOKEN_TTL_HOURS = 1
_VERIFY_TOKEN_TTL_HOURS = 24
_VERIFY_RESEND_COOLDOWN_SECONDS = 60

logger = logging.getLogger("signwave")

router = APIRouter(tags=["Auth"])


def _send_verification_email(db: Session, user: User) -> None:
    """Replaces any previous verification token of the user and emails a new link."""
    db.query(EmailVerificationToken).filter_by(user_id=user.id).delete()

    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=_VERIFY_TOKEN_TTL_HOURS)
    db.add(EmailVerificationToken(user_id=user.id, token=token, expires_at=expires_at))
    db.commit()

    lang = user.settings.language if user.settings else "uk"
    try:
        send_email_verification(user.email, user.username, token, lang=lang)  # type: ignore
    except Exception as e:
        logger.error(f"verification email failed for {user.email}: {e}")


# ---------------- REGISTER ----------------

@router.post("/register")
def register(data: RegisterRequest, request: Request, db: Session = Depends(get_db)):

    username = data.username
    email = data.email
    password = data.password

    ip = rate_limiter.client_ip(request)
    account = rate_limiter.normalize_account(email)
    rate_limiter.check(db, "register", ip, account)
    rate_limiter.record(db, "register", ip, account, success=False)

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

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    _send_verification_email(db, new_user)

    return {
        "message": "Registration successful. Please check your email to confirm your address."
    }


# ---------------- LOGIN ----------------

@router.post("/login")
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):

    username = data.username
    password = data.password

    ip = rate_limiter.client_ip(request)
    account = rate_limiter.normalize_account(username)
    rate_limiter.check(db, "login", ip, account)

    user = db.query(User).filter(User.username == username).first()

    if not user or not check_password_hash(str(user.password_hash), password):
        rate_limiter.record(db, "login", ip, account, success=False)
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    rate_limiter.record(db, "login", ip, account, success=True)

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
def google_login(data: GoogleLoginRequest, request: Request, db: Session = Depends(get_db)):
    access_token = data.access_token

    ip = rate_limiter.client_ip(request)
    rate_limiter.check(db, "google", ip, None)

    # Get user info from Google
    resp = http_requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"}
    )
    if resp.status_code != 200:
        rate_limiter.record(db, "google", ip, None, success=False)
        raise HTTPException(status_code=401, detail="Invalid Google token")

    info = resp.json()
    google_id = info.get("sub")
    email = info.get("email")
    name = info.get("name") or email.split("@")[0]
    avatar_url = info.get("picture")

    if not google_id or not email:
        raise HTTPException(status_code=400, detail="Google account missing required fields")

    if info.get("email_verified") is not True:
        raise HTTPException(status_code=400, detail="Google account email is not verified")

    # Find or create user
    user = db.query(User).filter(User.google_id == google_id).first()

    if not user:
        # Check if email already exists (regular account)
        user = db.query(User).filter(User.email == email).first()
        if user:
            # Link Google ID to existing account
            user.google_id = google_id  # type: ignore
            user.is_email_verified = True  # type: ignore
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
                is_email_verified=True,
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
def forgot_password(data: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    ip = rate_limiter.client_ip(request)
    account = rate_limiter.normalize_account(data.email)
    rate_limiter.check(db, "forgot", ip, account)
    rate_limiter.record(db, "forgot", ip, account, success=False)

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
    # The reset link was delivered to this email, so the user owns it
    user.is_email_verified = True  # type: ignore
    db.delete(reset_token)
    db.commit()

    return {"message": "Password updated successfully"}


# ---------------- VERIFY EMAIL ----------------

@router.post("/verify-email")
def verify_email(data: VerifyEmailRequest, db: Session = Depends(get_db)):
    verify_token = db.query(EmailVerificationToken).filter_by(token=data.token).first()

    if not verify_token or verify_token.expires_at < datetime.utcnow():
        if verify_token:
            db.delete(verify_token)
            db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = db.query(User).filter_by(id=verify_token.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.is_email_verified = True  # type: ignore
    db.delete(verify_token)
    db.commit()

    return {"message": "Email verified successfully"}


# ---------------- RESEND VERIFICATION ----------------

@router.post("/resend-verification")
def resend_verification(
    request: Request,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_email_verified:
        raise HTTPException(status_code=400, detail="Email is already verified")

    ip = rate_limiter.client_ip(request)
    account = str(user.id)
    rate_limiter.check(db, "resend", ip, account)

    last_token = db.query(EmailVerificationToken).filter_by(user_id=user.id).first()
    cooldown = timedelta(seconds=_VERIFY_RESEND_COOLDOWN_SECONDS)
    if last_token and last_token.created_at and datetime.utcnow() - last_token.created_at < cooldown:
        remaining = max(1, int((cooldown - (datetime.utcnow() - last_token.created_at)).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="Please wait a minute before requesting another email",
            headers={"Retry-After": str(remaining)},
        )

    rate_limiter.record(db, "resend", ip, account, success=False)
    _send_verification_email(db, user)

    return {"message": "Verification email sent"}