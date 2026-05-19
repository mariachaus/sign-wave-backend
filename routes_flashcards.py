from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import Gesture, GestureI18n, UserGestureStat, UserErrorLog
from database_connection import get_db
from dependencies import get_current_user_id
from gesture_stat_engine import update_gesture_stat

router = APIRouter(prefix="/flashcards", tags=["Flashcards"])


class ReviewRequest(BaseModel):
    known: bool


@router.get("/today")
def get_flashcards_today(
    lang: str = "uk",
    all: bool = False,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    query = db.query(UserGestureStat).filter(UserGestureStat.user_id == user_id)
    if not all:
        query = query.filter(
            or_(
                UserGestureStat.next_review_at <= now,
                UserGestureStat.next_review_at == None,
            )
        )
    else:
        query = query.filter(UserGestureStat.correct_count >= 1)

    stats = query.all()

    if not stats:
        return {"cards": [], "total_learned": _total_learned(user_id, db)}

    stat_map = {s.gesture_id: s for s in stats}
    gesture_ids = list(stat_map.keys())

    rows = (
        db.query(Gesture, GestureI18n)
        .join(GestureI18n, Gesture.id == GestureI18n.gesture_id)
        .filter(Gesture.id.in_(gesture_ids), GestureI18n.language_code == lang)
        .all()
    )

    cards = []
    for g, gi in rows:
        s = stat_map[g.id]
        cards.append({
            "id": g.id,
            "name": gi.name,
            "description": gi.description or "",
            "illustration_url": g.illustration_url or g.thumbnail_url,
            "mastery_level": s.mastery_level or 0,
            "correct_count": s.correct_count or 0,
        })

    return {"cards": cards, "total_learned": _total_learned(user_id, db)}


@router.post("/{gesture_id}/review")
def review_flashcard(
    gesture_id: int,
    payload: ReviewRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    update_gesture_stat(user_id, gesture_id, correct=payload.known, db=db)

    if not payload.known:
        db.add(UserErrorLog(
            user_id=user_id,
            gesture_id=gesture_id,
            error_type='flashcard_unknown',
        ))

    db.commit()
    return {"ok": True}


@router.get("/stats")
def get_flashcard_stats(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    due = db.query(UserGestureStat).filter(
        UserGestureStat.user_id == user_id,
        or_(
            UserGestureStat.next_review_at <= now,
            UserGestureStat.next_review_at == None,
        ),
    ).count()
    return {"due_today": due, "total_learned": _total_learned(user_id, db)}


def _total_learned(user_id: int, db: Session) -> int:
    return db.query(UserGestureStat).filter(
        UserGestureStat.user_id == user_id,
        UserGestureStat.correct_count >= 1,
    ).count()
