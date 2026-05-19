from datetime import datetime, timezone
from sqlalchemy.orm import Session
from database import Achievement, UserAchievement, User, UserStreak, UserLesson, Lesson, UserXPLog, UserGestureStat

_SHIELD_ACHIEVEMENTS = {3, 4, 5, 9, 10, 11}
_LEVEL_MASTER = {1: 9, 2: 10, 3: 11}


def _already_earned(user_id: int, ach_id: int, db: Session) -> bool:
    return db.query(UserAchievement).filter_by(
        user_id=user_id, achievement_id=ach_id
    ).first() is not None


def _try_award(user_id: int, ach_id: int, db: Session, user: User, streak) -> dict | None:
    if _already_earned(user_id, ach_id, db):
        return None
    ach = db.query(Achievement).filter_by(id=ach_id, is_active=True).first()
    if not ach:
        return None
    db.add(UserAchievement(
        user_id=user_id,
        achievement_id=ach_id,
        earned_at=datetime.now(timezone.utc),
    ))
    user.total_xp = (user.total_xp or 0) + ach.points_awarded
    db.add(UserXPLog(
        user_id=user_id,
        amount=ach.points_awarded,
        source_type="achievement",
        source_id=ach_id,
    ))
    if ach_id in _SHIELD_ACHIEVEMENTS and streak:
        streak.freeze_shields_count = min((streak.freeze_shields_count or 0) + 1, 2)
    return {
        "id": ach.id,
        "title": ach.title,
        "icon_url": ach.icon_url,
        "points_awarded": ach.points_awarded,
    }


def _check_streak(user_id: int, db: Session, user: User) -> list[dict]:
    streak = db.query(UserStreak).filter_by(user_id=user_id, is_current=True).first()
    if not streak:
        return []
    length = streak.streak_length or 0
    results = []
    for days, ach_id in [(3, 2), (7, 3), (14, 4), (30, 5), (100, 6)]:
        if length >= days:
            r = _try_award(user_id, ach_id, db, user, streak)
            if r:
                results.append(r)
    return results


def _check_signs(user_id: int, db: Session, user: User) -> list[dict]:
    signs_learned = db.query(UserGestureStat).filter(
        UserGestureStat.user_id == user_id,
        UserGestureStat.correct_count >= 1,
    ).count()
    results = []
    for count, ach_id in [(1, 13), (10, 14), (25, 15), (50, 16)]:
        if signs_learned >= count:
            r = _try_award(user_id, ach_id, db, user, None)
            if r:
                results.append(r)
    return results


def check_after_practice(user_id: int, db: Session) -> list[dict]:
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        return []
    results = []
    total = user.total_practices or 0
    for count, ach_id in [(1, 17), (5, 18), (10, 19)]:
        if total >= count:
            r = _try_award(user_id, ach_id, db, user, None)
            if r:
                results.append(r)
    results.extend(_check_streak(user_id, db, user))
    results.extend(_check_signs(user_id, db, user))
    return results


def check_after_lesson(user_id: int, lesson_id: int, hearts_remaining: int, db: Session) -> list[dict]:
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        return []
    results = []

    if hearts_remaining >= 5:
        r = _try_award(user_id, 12, db, user, None)
        if r:
            results.append(r)

    completed_count = db.query(UserLesson).filter_by(user_id=user_id, is_completed=True).count()
    for count, ach_id in [(1, 7), (5, 8)]:
        if completed_count >= count:
            r = _try_award(user_id, ach_id, db, user, None)
            if r:
                results.append(r)

    lesson = db.query(Lesson).filter_by(id=lesson_id).first()
    if lesson and lesson.level_id:
        ach_id = _LEVEL_MASTER.get(lesson.level_id)
        if ach_id:
            streak = db.query(UserStreak).filter_by(user_id=user_id, is_current=True).first()
            total_in_level = db.query(Lesson).filter_by(
                level_id=lesson.level_id, is_active=True
            ).count()
            completed_in_level = (
                db.query(UserLesson)
                .join(Lesson, UserLesson.lesson_id == Lesson.id)
                .filter(
                    UserLesson.user_id == user_id,
                    UserLesson.is_completed == True,
                    Lesson.level_id == lesson.level_id,
                )
                .count()
            )
            if total_in_level > 0 and completed_in_level >= total_in_level:
                r = _try_award(user_id, ach_id, db, user, streak)
                if r:
                    results.append(r)

    results.extend(_check_streak(user_id, db, user))
    results.extend(_check_signs(user_id, db, user))
    return results
