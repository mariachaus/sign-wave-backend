import math
import itertools
import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from datetime import datetime, timedelta, timezone

from db.connection import get_db
from db.models import (
    Lesson, LessonI18n, LessonContent, LessonGesturesPool,
    Gesture, GestureI18n, UserLesson, User, UserErrorLog,
    Level, LevelI18n, UserGestureStat, UserStreak, UserXPLog
)
from routes.daily import update_task_progress
from services.achievement_engine import check_after_practice, check_after_lesson
from services.gesture_stat_engine import update_gesture_stat
from schemas import LessonStartResponse, LessonCompleteRequest, ErrorDetail
from pydantic import BaseModel

class PracticeCompleteRequest(BaseModel):
    errors: list[ErrorDetail] = []

from core.dependencies import get_current_user_id

router = APIRouter(prefix="/lessons", tags=["Lessons"])

_STREAK_MILESTONES = {7: 50, 14: 75, 30: 100, 60: 150, 100: 300}


def _streak_xp(current_streak: int) -> int:
    return 15 + _STREAK_MILESTONES.get(current_streak, 0)


def _update_streak(user_id: int, db: Session) -> int:
    """Оновлює стрік юзера. Повертає XP зароблений за активність (0 якщо вже рахувалось сьогодні)."""
    now = datetime.utcnow()
    today = now.date()

    streak = db.query(UserStreak).filter(
        UserStreak.user_id == user_id,
        UserStreak.is_current == True,
    ).first()

    if not streak:
        streak = UserStreak(
            user_id=user_id,
            streak_length=1,
            last_activity_at=now,
            started_at=today,
            is_current=True,
            freeze_shields_count=0,
        )
        db.add(streak)
        return _streak_xp(1)

    last_date = streak.last_activity_at.date() if streak.last_activity_at else None  # type: ignore

    if last_date == today:
        return 0  # вже рахувалось сьогодні

    if last_date == today - timedelta(days=1):
        streak.streak_length = (streak.streak_length or 0) + 1  # type: ignore
    else:
        gap = (today - last_date).days if last_date else 9999
        if gap == 2 and (streak.freeze_shields_count or 0) > 0:  # type: ignore
            streak.freeze_shields_count = streak.freeze_shields_count - 1  # type: ignore
            streak.streak_length = (streak.streak_length or 0) + 1  # type: ignore
        else:
            # archive the broken streak
            streak.ended_at = last_date  # type: ignore
            streak.is_current = False  # type: ignore
            prev_shields = streak.freeze_shields_count or 0  # type: ignore
            streak = UserStreak(
                user_id=user_id,
                streak_length=1,
                last_activity_at=now,
                started_at=today,
                is_current=True,
                freeze_shields_count=prev_shields,
            )
            db.add(streak)
            return _streak_xp(1)

    streak.last_activity_at = now  # type: ignore

    return _streak_xp(streak.streak_length)  # type: ignore


# ---------------- LEVELS WITH PROGRESS ----------------

@router.get("/levels")
def get_levels_with_progress(
    lang: str = "en",
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    levels = db.query(Level, LevelI18n).join(
        LevelI18n, Level.id == LevelI18n.level_id
    ).filter(
        Level.is_active == True,
        LevelI18n.language_code == lang
    ).order_by(Level.id).all()

    completed_ids = {
        ul.lesson_id for ul in
        db.query(UserLesson).filter(
            UserLesson.user_id == user_id,
            UserLesson.is_completed == True
        ).all()
    }

    result = []
    for level, level_trans in levels:
        lessons_query = db.query(Lesson, LessonI18n).join(
            LessonI18n, Lesson.id == LessonI18n.lesson_id
        ).filter(
            Lesson.level_id == level.id,
            Lesson.is_active == True,
            LessonI18n.language_code == lang
        ).order_by(Lesson.order_index).all()

        lessons_data = []
        prev_completed = True  # first lesson is always unlocked

        for lesson, lesson_trans in lessons_query:
            is_completed = lesson.id in completed_ids
            is_locked = not prev_completed
            lessons_data.append({
                "id": lesson.id,
                "name": lesson_trans.name,
                "description": lesson_trans.description or "",
                "order_index": lesson.order_index,
                "is_completed": is_completed,
                "is_locked": is_locked,
            })
            prev_completed = is_completed

        result.append({
            "id": level.id,
            "name": level_trans.name,
            "description": level_trans.description or "",
            "lessons": lessons_data,
        })

    return result


# ---------------- NEXT LESSON ----------------

@router.get("/next")
def get_next_lesson(
    lang: str = "en",
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    completed_ids = {
        ul.lesson_id for ul in
        db.query(UserLesson).filter(
            UserLesson.user_id == user_id,
            UserLesson.is_completed == True
        ).all()
    }

    levels = db.query(Level).filter(Level.is_active == True).order_by(Level.id).all()

    prev_completed = True
    for level in levels:
        lessons = db.query(Lesson).filter(
            Lesson.level_id == level.id,
            Lesson.is_active == True
        ).order_by(Lesson.order_index).all()

        for lesson in lessons:
            is_completed = lesson.id in completed_ids
            is_locked = not prev_completed

            if not is_locked and not is_completed:
                level_trans = db.query(LevelI18n).filter(
                    LevelI18n.level_id == level.id,
                    LevelI18n.language_code == lang
                ).first()
                lesson_trans = db.query(LessonI18n).filter(
                    LessonI18n.lesson_id == lesson.id,
                    LessonI18n.language_code == lang
                ).first()
                return {
                    "lesson_id": lesson.id,
                    "lesson_name": lesson_trans.name if lesson_trans else f"Lesson {lesson.id}",
                    "level_name": level_trans.name if level_trans else f"Level {level.id}",
                }

            prev_completed = is_completed

    return None


# ---------------- PRACTICE GESTURE ----------------

@router.get("/practice/{gesture_id}", response_model=LessonStartResponse)
def practice_gesture(
    gesture_id: int,
    lang: str = "en",
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    res = db.query(Gesture, GestureI18n).join(
        GestureI18n, Gesture.id == GestureI18n.gesture_id
    ).filter(
        Gesture.id == gesture_id,
        Gesture.is_active == True,
        GestureI18n.language_code == lang
    ).first()
    if not res:
        raise HTTPException(status_code=404, detail="Gesture not found")
    gesture, gi = res

    def _g_local(g, g_i):
        return {
            "id": g.id, "name": g_i.name,
            "illustration_url": g.illustration_url or g.thumbnail_url,
            "description": g_i.description or "", "model_label": g.model_label,
        }

    target = _g_local(gesture, gi)

    # Пул варіантів: вивчені жести юзера + fill до мін 4
    learned_ids = {
        s.gesture_id for s in
        db.query(UserGestureStat).filter(
            UserGestureStat.user_id == user_id,
            UserGestureStat.correct_count >= 1
        ).all()
    }
    extra_ids = learned_ids - {gesture_id} # type: ignore

    extra_raw = (
        db.query(Gesture, GestureI18n)
          .join(GestureI18n, Gesture.id == GestureI18n.gesture_id)
          .filter(Gesture.id.in_(extra_ids), Gesture.is_active == True, GestureI18n.language_code == lang)
          .limit(5).all()
        if extra_ids else []
    )

    seen = {gesture_id}
    all_pool = [target]
    for g, g_i in extra_raw:
        if g.id not in seen:
            seen.add(g.id)
            all_pool.append(_g_local(g, g_i))

    if len(all_pool) < 10:
        fill_raw = db.query(Gesture, GestureI18n)\
            .join(GestureI18n, Gesture.id == GestureI18n.gesture_id)\
            .filter(Gesture.id.notin_(seen), GestureI18n.language_code == lang)\
            .order_by(func.random())\
            .limit(10 - len(all_pool)).all()
        for g, g_i in fill_raw:
            all_pool.append(_g_local(g, g_i))

    def _quiz_opts():
        distractors = [g for g in all_pool if g["id"] != target["id"]]
        return random.sample(distractors, min(3, len(distractors))) + [target]

    def _match_pool():
        others = [g for g in all_pool if g["id"] != target["id"]]
        return [target] + random.sample(others, min(3, len(others)))

    # Кроки: imitation першим, решта перемішано
    rest = [
        {"type": "quiz", "mode": "word_to_image", "target": target, "options": _quiz_opts()},
        {"type": "quiz", "mode": "word_to_image", "target": target, "options": _quiz_opts()},
        {"type": "quiz", "mode": "image_to_word", "target": target, "options": _quiz_opts()},
        {"type": "quiz", "mode": "image_to_word", "target": target, "options": _quiz_opts()},
        {"type": "recall", "gesture": target},
    ]
    if len(all_pool) >= 3:
        rest.append({"type": "matching", "gestures": _match_pool()})
        rest.append({"type": "matching", "gestures": _match_pool()})

    rest.append({"type": "imitation", "gesture": target})
    random.shuffle(rest)
    steps = rest

    return {"lesson_id": 0, "lesson_name": gi.name, "steps": steps}


@router.post("/practice/{gesture_id}/complete")
def complete_practice(
    gesture_id: int,
    payload: PracticeCompleteRequest = PracticeCompleteRequest(),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    streak_xp = _update_streak(user_id, db)
    user.total_xp = (user.total_xp or 0) + streak_xp  # type: ignore
    user.total_practices = (user.total_practices or 0) + 1  # type: ignore

    if streak_xp > 0:
        db.add(UserXPLog(user_id=user_id, amount=streak_xp, source_type="practice", source_id=gesture_id))

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[practice/complete] commit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    try:
        update_task_progress(user_id, "practice_completed", db, gesture_id=gesture_id, xp_gained=streak_xp)
    except Exception as e:
        print(f"[daily-tasks] update failed after practice: {e}")

    try:
        update_gesture_stat(user_id, gesture_id, correct=True, db=db)
        for err in payload.errors:
            if err.gesture_id != gesture_id:
                update_gesture_stat(user_id, err.gesture_id, correct=False, db=db)
            db.add(UserErrorLog(
                user_id=user_id,
                gesture_id=err.gesture_id,
                exercise_type_id=err.exercise_type_id,
                error_type=err.error_type,
            ))
        db.commit()
    except Exception as e:
        print(f"[gesture-stat] update failed after practice: {e}")
        db.rollback()

    new_achievements = []
    try:
        new_achievements = check_after_practice(user_id, db)
        if new_achievements:
            db.commit()
    except Exception as e:
        print(f"[achievements] check failed after practice: {e}")
        db.rollback()

    streak = db.query(UserStreak).filter(
        UserStreak.user_id == user_id,
        UserStreak.is_current == True,
    ).first()
    return {
        "streak_xp": streak_xp,
        "current_streak": streak.streak_length if streak else 1,
        "new_achievements": new_achievements,
    }


# ---------------- RANDOM LESSON ----------------

@router.get("/random", response_model=LessonStartResponse)
def random_lesson(
    lang: str = "en",
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    # Пул: вивчені жести юзера
    learned_ids = {
        s.gesture_id for s in
        db.query(UserGestureStat).filter(
            UserGestureStat.user_id == user_id,
            UserGestureStat.correct_count >= 1
        ).all()
    }

    pool_raw = (
        db.query(Gesture, GestureI18n)
          .join(GestureI18n, Gesture.id == GestureI18n.gesture_id)
          .filter(
              Gesture.id.in_(learned_ids),
              Gesture.is_active == True,
              GestureI18n.language_code == lang
          ).all()
        if learned_ids else []
    )

    seen = {g.id for g, _ in pool_raw}
    all_pool = [_g(g, gi) for g, gi in pool_raw]

    # Добираємо до мін 10 якщо вивчених мало
    if len(all_pool) < 10:
        fill_raw = db.query(Gesture, GestureI18n)\
            .join(GestureI18n, Gesture.id == GestureI18n.gesture_id)\
            .filter(
                Gesture.id.notin_(seen),
                GestureI18n.language_code == lang
            ).order_by(func.random())\
            .limit(10 - len(all_pool)).all()
        for g, gi in fill_raw:
            all_pool.append(_g(g, gi))

    if not all_pool:
        raise HTTPException(status_code=404, detail="No gestures available")

    # Рандомна вибірка фокус-жестів (3-7)
    n_focus = min(random.randint(3, 7), len(all_pool))
    focus_gestures = random.sample(all_pool, n_focus)

    # Рандомна кількість кроків (5-12)
    n_steps = random.randint(5, 12)

    steps = []

    # По одній imitation на кожен фокус-жест
    for gd in focus_gestures:
        steps.append({"type": "imitation", "gesture": gd})

    # Заповнюємо до n_steps
    remaining = max(0, n_steps - len(focus_gestures))
    cycle = itertools.cycle(focus_gestures)
    matching_count = 0

    for i in range(remaining):
        gd = next(cycle)
        r = random.random()
        if r < 0.35:
            mode = "word_to_image" if i % 2 == 0 else "image_to_word"
            steps.append({"type": "quiz", "mode": mode, "target": gd, "options": all_pool})
        elif r < 0.55 and len(all_pool) >= 3 and matching_count < 2:
            pool_slice = random.sample(all_pool, min(4, len(all_pool)))
            steps.append({"type": "matching", "gestures": pool_slice})
            matching_count += 1
        else:
            steps.append({"type": "recall", "gesture": gd})

    random.shuffle(steps)

    return {"lesson_id": -1, "lesson_name": "random", "steps": steps}


# ---------------- START LESSON ----------------

def _g(g, gi):
    """Серіалізує жест у словник для кроку вправи."""
    return {
        "id": g.id,
        "name": gi.name,
        "illustration_url": g.illustration_url or g.thumbnail_url,
        "description": gi.description or "",
        "model_label": g.model_label,
    }


@router.get("/{lesson_id}/start", response_model=LessonStartResponse)
def start_lesson(
    lesson_id: int,
    lang: str = "en",
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    # 1. Базова інформація про урок
    res = db.query(Lesson, LessonI18n).join(LessonI18n).filter(
        Lesson.id == lesson_id,
        LessonI18n.language_code == lang
    ).first()
    if not res:
        raise HTTPException(status_code=404, detail="Lesson not found")
    lesson, trans = res

    # 2. Блоки теорії
    theory_blocks = db.query(LessonContent).filter(
        LessonContent.lesson_id == lesson_id,
        LessonContent.language_code == lang
    ).order_by(LessonContent.order_index).all()

    # 3. Пул жестів уроку (з позначкою нового)
    lesson_raw = db.query(
        Gesture, GestureI18n, LessonGesturesPool.is_new_for_this_lesson
    ).join(GestureI18n, Gesture.id == GestureI18n.gesture_id)\
     .join(LessonGesturesPool, Gesture.id == LessonGesturesPool.gesture_id)\
     .filter(
        LessonGesturesPool.lesson_id == lesson_id,
        GestureI18n.language_code == lang
     ).all()

    new_dicts    = [_g(g, gi) for g, gi, is_new in lesson_raw if is_new]
    review_dicts = [_g(g, gi) for g, gi, is_new in lesson_raw if not is_new]
    lesson_dicts = new_dicts + review_dicts
    lesson_ids   = {g.id for g, _, __ in lesson_raw}

    # 4. Вивчені жести юзера (correct_count >= 1) — для квізу та підбору пар
    learned_ids = {
        s.gesture_id for s in
        db.query(UserGestureStat).filter(
            UserGestureStat.user_id == user_id,
            UserGestureStat.correct_count >= 1
        ).all()
    }
    extra_ids = learned_ids - lesson_ids

    extra_raw = (
        db.query(Gesture, GestureI18n)
          .join(GestureI18n, Gesture.id == GestureI18n.gesture_id)
          .filter(
              Gesture.id.in_(extra_ids),
              Gesture.is_active == True,
              GestureI18n.language_code == lang
          ).all()
        if extra_ids else []
    )

    # Загальний пул (урок + вивчені), дедуплікований
    seen = set(lesson_ids)
    all_pool = list(lesson_dicts)
    for g, gi in extra_raw:
        if g.id not in seen:
            seen.add(g.id)
            all_pool.append(_g(g, gi))

    # Якщо менше 10 — добираємо будь-які жести для варіантів квізу
    if len(all_pool) < 10:
        fill_raw = (
            db.query(Gesture, GestureI18n)
              .join(GestureI18n, Gesture.id == GestureI18n.gesture_id)
              .filter(
                  Gesture.id.notin_(seen),
                  GestureI18n.language_code == lang
              ).order_by(func.random())
              .limit(10 - len(all_pool)).all()
        )
        for g, gi in fill_raw:
            all_pool.append(_g(g, gi))

    # 4b. Випадкове розширення пулу повторення (~60% шанс)
    # Додаємо 2-3 "найслабших" або "найдавніше вчених" жестів до imitation
    spaced_extra: list = []
    if extra_ids and random.random() < 0.6:
        weak_stats = db.query(UserGestureStat).filter(
            UserGestureStat.user_id == user_id,
            UserGestureStat.gesture_id.in_(extra_ids)
        ).order_by(
            UserGestureStat.mastery_level.asc(),
            UserGestureStat.last_attempt_at.asc()
        ).limit(3).all()

        if weak_stats:
            weak_ids = {s.gesture_id for s in weak_stats}
            spaced_extra = [gd for gd in all_pool if gd["id"] in weak_ids]

    # Версії тільки з активними жестами — для вправ з камерою (imitation, recall)
    _active_ids      = {g.id for g, gi, is_new in lesson_raw if g.is_active}
    new_dicts_cam    = [gd for gd in new_dicts    if gd["id"] in _active_ids]
    review_dicts_cam = [gd for gd in review_dicts if gd["id"] in _active_ids]
    lesson_dicts_cam = new_dicts_cam + review_dicts_cam

    # review_pool для imitation = не-нові АКТИВНІ жести уроку + spaced_extra (без дублів)
    review_pool_ids = {gd["id"] for gd in review_dicts_cam}
    review_pool = review_dicts_cam + [gd for gd in spaced_extra if gd["id"] not in review_pool_ids]

    # 5. Генерація кроків
    N = len(lesson_dicts)
    total_interactive = math.ceil(N * 1.5)

    # Theory slides — завжди першими, порядок збережено
    theory_steps = []
    for block in theory_blocks:
        theory_steps.append({
            "type": "theory",
            "gesture": {
                "id": None,
                "name": block.title or trans.name,
                "illustration_url": block.image_url,
                "description": block.body_text,
                "model_label": None,
            },
            "content": block.body_text,
        })

    # Всі інтерактивні кроки збираємо окремо, потім перемішуємо
    interactive_steps = []

    # Imitation: по одній на кожен НОВИЙ активний жест + 1-3 рандомних з review_pool
    n_review_imit = min(random.randint(1, 3), len(review_pool))
    imit_sample = random.sample(review_pool, n_review_imit) if n_review_imit > 0 else []

    for gd in new_dicts_cam:
        interactive_steps.append({"type": "imitation", "gesture": gd})
    for gd in imit_sample:
        interactive_steps.append({"type": "imitation", "gesture": gd})

    imit_count = len(new_dicts_cam) + n_review_imit
    review_left = max(0, total_interactive - imit_count)

    # Matching (базова + ~50% шанс ще однієї)
    matching_pool = all_pool[:min(len(all_pool), 4)]
    if len(matching_pool) >= 3 and review_left > 0:
        interactive_steps.append({"type": "matching", "gestures": matching_pool})
        review_left -= 1
        if review_left > 0 and random.random() < 0.5:
            interactive_steps.append({"type": "matching", "gestures": matching_pool})
            review_left -= 1

    # Решта: quiz та recall
    if N > 0 and review_left > 0:
        cycle_quiz   = itertools.cycle(lesson_dicts)
        cycle_recall = itertools.cycle(lesson_dicts_cam) if lesson_dicts_cam else None
        for i in range(review_left):
            if i % 2 == 0:
                target = next(cycle_quiz)
                mode = "word_to_image" if (i // 2) % 2 == 0 else "image_to_word"
                interactive_steps.append({
                    "type": "quiz",
                    "mode": mode,
                    "target": target,
                    "options": all_pool,
                })
            elif cycle_recall:
                interactive_steps.append({"type": "recall", "gesture": next(cycle_recall)})
            else:
                target = next(cycle_quiz)
                interactive_steps.append({
                    "type": "quiz",
                    "mode": "image_to_word",
                    "target": target,
                    "options": all_pool,
                })

    # Рандомний бонус: 0-2 додаткових quiz зверху
    if N > 0 and random.random() < 0.5:
        bonus = random.randint(1, 2)
        cycle_bonus = itertools.cycle(lesson_dicts)
        for i in range(bonus):
            target = next(cycle_bonus)
            mode = "image_to_word" if i % 2 == 0 else "word_to_image"
            interactive_steps.append({
                "type": "quiz",
                "mode": mode,
                "target": target,
                "options": all_pool,
            })

    # Перемішуємо вправи випадково
    random.shuffle(interactive_steps)

    steps = theory_steps + interactive_steps

    # 6. Реєструємо спробу в user_lessons (не скидаємо completed якщо вже пройдено)
    now = datetime.now(timezone.utc)
    user_lesson = db.query(UserLesson).filter(
        UserLesson.user_id == user_id,
        UserLesson.lesson_id == lesson_id
    ).first()

    if not user_lesson:
        user_lesson = UserLesson(
            user_id=user_id,
            lesson_id=lesson_id,
            status='started',
            is_completed=False,
            total_attempts=1,
            started_at=now,
            last_attempt_at=now,
        )
        db.add(user_lesson)
    else:
        user_lesson.total_attempts = (user_lesson.total_attempts or 0) + 1  # type: ignore
        user_lesson.last_attempt_at = now  # type: ignore
        if not user_lesson.is_completed: # type: ignore
            user_lesson.status = 'started'  # type: ignore

    try:
        db.commit()
    except Exception:
        db.rollback()

    return {"lesson_id": lesson.id, "lesson_name": trans.name, "steps": steps}


# ---------------- COMPLETE LESSON ----------------
# Фіксуємо результат, нараховуємо XP та записуємо помилки


@router.post("/{lesson_id}/complete")
def complete_lesson(
    lesson_id: int,
    payload: LessonCompleteRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    # 1. Шукаємо прогрес
    user_lesson = db.query(UserLesson).filter(
        UserLesson.user_id == user_id,
        UserLesson.lesson_id == lesson_id
    ).first()

    now = datetime.now(timezone.utc)

    if not user_lesson:
        # Створюємо новий запис
        user_lesson = UserLesson(
            user_id=user_id,
            lesson_id=lesson_id,
            total_attempts=1,
            status='completed',
            is_completed=True,
            best_score=payload.score,
            last_attempt_at=now,
            completed_at=now
        )
        db.add(user_lesson)
    else:
        # Оновлюємо існуючий (використовуємо += 1 обережно для Pylance)
        user_lesson.total_attempts = (user_lesson.total_attempts or 0) + 1 # type: ignore # type: ignore
        user_lesson.last_attempt_at = now # type: ignore
        user_lesson.status = 'completed' # type: ignore
        user_lesson.is_completed = True # type: ignore

        # Перевірка рекорду
        if payload.score > (user_lesson.best_score or 0): # type: ignore
            user_lesson.best_score = payload.score # type: ignore

        # Якщо вперше пройшов — ставимо дату
        if user_lesson.completed_at is None:
            user_lesson.completed_at = now # type: ignore

    # 2. Нараховуємо XP + стрік
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    streak_xp = _update_streak(user_id, db)
    lesson_xp = payload.score + streak_xp
    user.total_xp = (user.total_xp or 0) + lesson_xp  # type: ignore
    current_xp = user.total_xp

    # 3. Логуємо XP
    if lesson_xp > 0:
        db.add(UserXPLog(user_id=user_id, amount=lesson_xp, source_type="lesson", source_id=lesson_id))

    # 4. Логуємо помилки
    if payload.errors:
        for err in payload.errors:
            db.add(UserErrorLog(
                user_id=user_id,
                lesson_id=lesson_id,
                gesture_id=err.gesture_id,
                exercise_type_id=err.exercise_type_id,
                error_type=err.error_type,
            ))

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save lesson progress")

    # 5. Щоденні завдання
    try:
        perfect = payload.hearts_remaining >= 5
        update_task_progress(user_id, "lesson_completed", db, xp_gained=lesson_xp, perfect=perfect)
    except Exception as e:
        print(f"[daily-tasks] update failed after lesson: {e}")

    # 6. Gesture stats для помилок
    if payload.errors:
        try:
            for err in payload.errors:
                update_gesture_stat(user_id, err.gesture_id, correct=False, db=db)
            db.commit()
        except Exception as e:
            print(f"[gesture-stat] update failed after lesson: {e}")
            db.rollback()

    new_achievements = []
    try:
        new_achievements = check_after_lesson(user_id, lesson_id, payload.hearts_remaining, db)
        if new_achievements:
            db.commit()
    except Exception as e:
        print(f"[achievements] check failed after lesson: {e}")
        db.rollback()

    streak = db.query(UserStreak).filter(
        UserStreak.user_id == user_id,
        UserStreak.is_current == True,
    ).first()
    return {
        "message": "Lesson progress saved",
        "new_total_xp": current_xp,
        "streak_xp": streak_xp,
        "current_streak": streak.streak_length if streak else 1,
        "new_achievements": new_achievements,
    }