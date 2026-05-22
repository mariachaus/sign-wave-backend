from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash

from db.connection import get_db
from db.models import User, UserSetting
from core.dependencies import get_current_user_id

router = APIRouter(tags=["Settings"])


# ---------------- GET SETTINGS ----------------

@router.get("/")
def get_settings(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    user = db.query(User).get(user_id)
    settings = db.query(UserSetting).filter_by(user_id=user_id).first()

    if not user or not settings:
        raise HTTPException(status_code=404, detail="Data not found")

    return {
        "profile": {
            "username": user.username,
            "email": user.email
        },
        "ui": {
            "theme": settings.theme,
            "language": settings.language,  # ДОДАНО: повертаємо мову з БД
            "landmark_color": settings.landmark_color,
            "connection_color": settings.connection_color,
            "is_landmarks_visible": settings.is_landmarks_visible,
            "font_size": float(settings.font_size_multiplier or 1.0), # type: ignore
            "email_notifications": settings.is_email_notifications_enabled,
            "is_mirror_view_enabled": settings.is_mirror_view_enabled
        }
    }


# ---------------- UPDATE UI ----------------

@router.put("/update-ui")
def update_ui(
    data: dict,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    settings = db.query(UserSetting).filter_by(user_id=user_id).first()

    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found")

    # ДОДАНО: обробка поля language
    if "language" in data:
        settings.language = data["language"]

    if "theme" in data:
        settings.theme = data["theme"]

    if "landmark_color" in data:
        settings.landmark_color = data["landmark_color"]

    if "connection_color" in data:
        settings.connection_color = data["connection_color"]

    if "is_landmarks_visible" in data:
        settings.is_landmarks_visible = data["is_landmarks_visible"]

    if "font_size" in data:
        settings.font_size_multiplier = data["font_size"]

    if "email_notifications" in data:
        settings.is_email_notifications_enabled = data["email_notifications"]

    if "is_mirror_view_enabled" in data:
        settings.is_mirror_view_enabled = data["is_mirror_view_enabled"]

    # Оновлюємо мітку часу редагування
    settings.updated_at = datetime.utcnow() # type: ignore

    db.commit()

    return {"message": "UI settings updated"}

# ---------------- UPDATE PROFILE ----------------

@router.put("/update-profile")
def update_profile(
    data: dict,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):

    user = db.query(User).get(user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_username = data.get("username")

    if new_username and new_username != user.username:
        if db.query(User).filter(User.username == new_username).first():
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = new_username

    new_email = data.get("email")

    if new_email and new_email != user.email:
        if db.query(User).filter(User.email == new_email).first():
            raise HTTPException(status_code=400, detail="Email already taken")
        user.email = new_email

    db.commit()

    return {"message": "Profile updated successfully"}


# ---------------- CHANGE PASSWORD ----------------

@router.put("/change-password")
def change_password(
    data: dict,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):

    user = db.query(User).get(user_id)

    old_pw = data.get("old_password") or ""
    new_pw = data.get("new_password") or ""

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.password_hash:
        raise HTTPException(status_code=400, detail="Google users cannot change password")

    if not check_password_hash(str(user.password_hash), old_pw):
        raise HTTPException(status_code=400, detail="Incorrect old password")

    user.password_hash = generate_password_hash(new_pw)

    db.commit()

    return {"message": "Password changed successfully"}


# ---------------- DELETE ACCOUNT ----------------

@router.delete("/delete-account")
def delete_account(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):

    user = db.query(User).get(user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()

    return {"message": "Account deleted forever"}