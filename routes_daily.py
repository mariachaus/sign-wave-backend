import random
from datetime import date, datetime, time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from database_connection import get_db
from database import UserDailyTask, DailyTaskTemplate, Gesture, GestureI18n, UserXPLog, User, UserGestureStat, UserStreak
from dependencies import get_current_user_id

router = APIRouter(prefix="/daily-tasks", tags=["Daily Tasks"])

_TYPE_WEIGHTS = {
    "complete_lesson":         3,
    "complete_lesson_perfect": 1,
    "practice_gesture":        3,
    "practice_count":          2,
    "earn_xp":                 2,
}


def _pick_gesture(user_id: int, db: Session):
    learned = [
        s.gesture_id for s in
        db.query(UserGestureStat).filter(
            UserGestureStat.user_id == user_id,
            UserGestureStat.correct_count >= 1
        ).limit(50).all()
    ]
    if learned:
        return random.choice(learned)
    ids = [row.id for row in db.query(Gesture.id).filter(Gesture.is_active == True).all()]
    return random.choice(ids) if ids else None


def _generate_tasks(user_id: int, db: Session):
    templates = db.query(DailyTaskTemplate).filter(DailyTaskTemplate.is_active == True).all()
    if not templates:
        return

    # Group templates by type
    by_type: dict = {}
    for tmpl in templates:
        by_type.setdefault(tmpl.task_type, []).append(tmpl)

    # Build weighted pool of types, shuffle, pick 3 distinct
    pool = []
    for task_type, weight in _TYPE_WEIGHTS.items():
        if task_type in by_type:
            pool.extend([task_type] * weight)
    random.shuffle(pool)

    chosen_types, seen = [], set()
    for t in pool:
        if t not in seen and len(chosen_types) < 3:
            chosen_types.append(t)
            seen.add(t)

    today = date.today()
    db.query(UserDailyTask).filter(
        UserDailyTask.user_id == user_id,
        UserDailyTask.assigned_at < today,
    ).delete()

    for task_type in chosen_types:
        template = random.choice(by_type[task_type])
        target_id = _pick_gesture(user_id, db) if task_type == "practice_gesture" else None
        db.add(UserDailyTask(
            user_id=user_id,
            task_template_id=template.id,
            target_id=target_id,
            current_value=0,
            is_completed=False,
            assigned_at=today,
        ))
    db.commit()


def _today_tasks(user_id: int, db: Session) -> list:
    return db.query(UserDailyTask).filter(
        UserDailyTask.user_id == user_id,
        UserDailyTask.assigned_at == date.today(),
    ).all()


def _load_templates(tasks: list, db: Session) -> dict:
    ids = [t.task_template_id for t in tasks]
    return {
        tmpl.id: tmpl
        for tmpl in db.query(DailyTaskTemplate).filter(DailyTaskTemplate.id.in_(ids)).all()
    }


def update_task_progress(
    user_id: int,
    event: str,
    db: Session,
    gesture_id=None,
    xp_gained: int = 0,
    perfect: bool = False,
):
    tasks = _today_tasks(user_id, db)
    if not tasks:
        return

    templates = _load_templates(tasks, db)
    changed = False

    for task in tasks:
        if task.is_completed:
            continue
        tmpl = templates.get(task.task_template_id)
        if not tmpl:
            continue

        t = tmpl.task_type
        target = tmpl.target_value or 1
        matched = False

        if t == "complete_lesson" and event == "lesson_completed":
            task.current_value = min((task.current_value or 0) + 1, target)
            matched = True

        elif t == "complete_lesson_perfect" and event == "lesson_completed" and perfect:
            task.current_value = min((task.current_value or 0) + 1, target)
            matched = True

        elif t == "practice_gesture" and event == "practice_completed" and gesture_id == task.target_id:
            task.current_value = 1
            matched = True

        elif t == "practice_count" and event == "practice_completed":
            task.current_value = min((task.current_value or 0) + 1, target)
            matched = True

        elif t == "earn_xp" and xp_gained > 0:
            today_start = datetime.combine(date.today(), time.min)
            today_xp = db.query(func.sum(UserXPLog.amount)).filter(
                UserXPLog.user_id == user_id,
                UserXPLog.created_at >= today_start,
            ).scalar() or 0
            task.current_value = min(int(today_xp), target)
            matched = True

        if matched:
            changed = True
            if (task.current_value or 0) >= target:
                task.is_completed = True
                user = db.get(User, user_id)
                if user and tmpl.xp_reward:
                    user.total_xp = (user.total_xp or 0) + tmpl.xp_reward  # type: ignore
                    db.add(UserXPLog(
                        user_id=user_id,
                        amount=tmpl.xp_reward,
                        source_type="daily_task",
                        source_id=task.id,
                    ))

    if changed:
        db.commit()

        # Якщо всі завдання виконані — 30% шанс на Freeze Shield (макс 2)
        all_tasks = _today_tasks(user_id, db)
        if len(all_tasks) >= 3 and all(t.is_completed for t in all_tasks):
            if random.random() < 0.30:
                streak = db.query(UserStreak).filter_by(user_id=user_id, is_current=True).first()
                if streak and (streak.freeze_shields_count or 0) < 2:
                    streak.freeze_shields_count = (streak.freeze_shields_count or 0) + 1
                    db.commit()


@router.get("/")
def get_daily_tasks(
    lang: str = "en",
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    try:
        tasks = _today_tasks(user_id, db)
        if not tasks:
            _generate_tasks(user_id, db)
            tasks = _today_tasks(user_id, db)
    except Exception as e:
        print(f"[daily-tasks] error for user {user_id}: {e}")
        raise

    templates = _load_templates(tasks, db)
    result = []

    for task in tasks:
        tmpl = templates.get(task.task_template_id)
        if not tmpl:
            continue

        gesture_name = None
        if tmpl.task_type == "practice_gesture" and task.target_id:
            gi = db.query(GestureI18n).filter(
                GestureI18n.gesture_id == task.target_id,
                GestureI18n.language_code == lang,
            ).first()
            gesture_name = gi.name if gi else None

        result.append({
            "id": task.id,
            "task_type": tmpl.task_type,
            "target_value": tmpl.target_value,
            "current_value": task.current_value or 0,
            "xp_reward": tmpl.xp_reward,
            "is_completed": task.is_completed,
            "target_id": task.target_id,
            "gesture_name": gesture_name,
        })

    return result
