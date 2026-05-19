from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
import cloudinary
import cloudinary.uploader
import os
from dotenv import load_dotenv

load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

from dependencies import get_current_user_id
from database_connection import get_db
from database import (
    User,
    UserStreak,
    UserErrorLog,
    UserGestureStat,
    UserAchievement,
    Achievement
)

router = APIRouter(tags=["User"])


# ---------------- PROFILE ----------------

@router.get("/profile")
def get_profile(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):

    try:
        user = db.get(User, user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # 1. errors count
        errors_made = db.query(UserErrorLog).filter_by(user_id=user_id).count()

        # 2. learned gestures
        signs_learned = db.query(UserGestureStat).filter(
            UserGestureStat.user_id == user_id,
            UserGestureStat.correct_count >= 1
        ).count()

        # 3. total correct answers
        total_correct = db.query(
            func.sum(UserGestureStat.correct_count)
        ).filter(UserGestureStat.user_id == user_id).scalar() or 0

        # 4. achievements (JOIN)
        achievements_query = (
            db.query(Achievement, UserAchievement.earned_at)
            .join(UserAchievement, Achievement.id == UserAchievement.achievement_id)
            .filter(UserAchievement.user_id == user_id)
            .order_by(UserAchievement.earned_at.desc())
            .limit(5)
            .all()
        )

        ach_list = [
            {
                "id": ach.id,
                "title": ach.title,
                "description": ach.description,
                "icon_url": ach.icon_url,
                "points_awarded": ach.points_awarded,
                "earned_at": earned_at.isoformat()
            }
            for ach, earned_at in achievements_query
        ]

        return {
            "username": user.username,
            "joined_at": user.created_at.strftime("%d %B %Y") if user.created_at else "Unknown", # type: ignore
            "total_xp": user.total_xp,
            "avatar_url": user.avatar_url,
            "role": user.role,
            "current_streak": user.streak.streak_length if user.streak else 0,
            "longest_streak": db.query(func.max(UserStreak.streak_length)).filter(
                UserStreak.user_id == user_id
            ).scalar() or 0,
            "achievements": ach_list,
            "stats": {
                "errors_made": errors_made,
                "errors_corrected": int(total_correct),
                "signs_learned": signs_learned
            }
        }

    except Exception as e:
        print(f"Error in get_profile: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


# ---------------- UPLOAD AVATAR ----------------

@router.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status_code=400, detail="Only JPEG, PNG or WebP images are allowed")

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be under 5 MB")

    result = cloudinary.uploader.upload(
        contents,
        folder="signwave/avatars",
        public_id=f"user_{user_id}",
        overwrite=True,
        transformation=[{"width": 400, "height": 400, "crop": "fill", "gravity": "face"}],
    )

    avatar_url = result["secure_url"]

    user = db.get(User, user_id)
    user.avatar_url = avatar_url  # type: ignore
    db.commit()

    return {"avatar_url": avatar_url}


# ---------------- ALL ACHIEVEMENTS ----------------

@router.get("/achievements")
def get_all_achievements(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    all_achievements = db.query(Achievement).filter(Achievement.is_active == True).all()

    earned_map = {
        ua.achievement_id: ua.earned_at
        for ua in db.query(UserAchievement).filter(UserAchievement.user_id == user_id).all()
    }

    result = [
        {
            "id": ach.id,
            "title": ach.title,
            "description": ach.description,
            "icon_url": ach.icon_url,
            "points_awarded": ach.points_awarded,
            "earned": ach.id in earned_map,
            "earned_at": earned_map[ach.id].isoformat() if ach.id in earned_map else None,
        }
        for ach in all_achievements
    ]

    result.sort(key=lambda x: (not x["earned"], x["id"]))
    return result


# ---------------- STREAK ----------------

@router.get("/streak")
def get_streak(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    streak = db.query(UserStreak).filter(
        UserStreak.user_id == user_id,
        UserStreak.is_current == True,
    ).first()
    if not streak:
        return {"current_streak": 0, "longest_streak": 0, "freeze_shields": 0}

    current = streak.streak_length or 0
    longest = db.query(func.max(UserStreak.streak_length)).filter(
        UserStreak.user_id == user_id
    ).scalar() or 0

    return {
        "current_streak": current,
        "longest_streak": longest,
        "freeze_shields": streak.freeze_shields_count or 0,
    }


# ---------------- STREAK CALENDAR ----------------

@router.get("/streak-calendar")
def get_streak_calendar(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    all_streaks = (
        db.query(UserStreak)
        .filter(UserStreak.user_id == user_id)
        .order_by(UserStreak.started_at)
        .all()
    )
    if not all_streaks:
        return {"streak_periods": [], "current_streak": 0, "longest_streak": 0}

    longest = db.query(func.max(UserStreak.streak_length)).filter(
        UserStreak.user_id == user_id
    ).scalar() or 0

    current_row = next((s for s in all_streaks if s.is_current), None)

    periods = []
    for s in all_streaks:
        if not s.started_at:
            continue
        if s.ended_at:
            end_iso = s.ended_at.isoformat()
        elif s.last_activity_at:
            end_iso = s.last_activity_at.date().isoformat()
        else:
            end_iso = date.today().isoformat()
        periods.append({
            "started_at": s.started_at.isoformat(),
            "ended_at": end_iso,
            "is_current": bool(s.is_current),
            "streak_length": s.streak_length or 0,
        })

    return {
        "streak_periods": periods,
        "current_streak": current_row.streak_length if current_row else 0,
        "longest_streak": longest,
    }