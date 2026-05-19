from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import requests as http_requests

from werkzeug.security import generate_password_hash, check_password_hash

from database_connection import get_db
from database import User, UserSetting, UserStreak, UserAchievement, Achievement

from auth_utils import create_access_token
from schemas import RegisterRequest, LoginRequest, GoogleLoginRequest

GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

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