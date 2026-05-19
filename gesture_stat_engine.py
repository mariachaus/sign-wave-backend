from datetime import datetime, timezone, timedelta
from math import ceil
from sqlalchemy.orm import Session
from database import UserGestureStat

# SM-2 adapted: base intervals (days) per mastery stage after a correct review
_STAGE_INTERVALS = {0: 1, 1: 6, 2: 14, 3: 30}


def _ease_factor(correct: int, total: int) -> float:
    """Ease factor in [1.3, 2.5] based on historical success rate."""
    if total == 0:
        return 2.5
    return max(1.3, min(2.5, 1.3 + (correct / total) * 1.2))


def update_gesture_stat(user_id: int, gesture_id: int, correct: bool, db: Session) -> None:
    now = datetime.now(timezone.utc)
    stat = db.query(UserGestureStat).filter_by(user_id=user_id, gesture_id=gesture_id).first()

    if not stat:
        stat = UserGestureStat(
            user_id=user_id,
            gesture_id=gesture_id,
            correct_count=0,
            error_count=0,
            mastery_level=0,
            created_at=now,
        )
        db.add(stat)

    if correct:
        stat.correct_count = (stat.correct_count or 0) + 1  # type: ignore
    else:
        stat.error_count = (stat.error_count or 0) + 1  # type: ignore

    stat.last_attempt_at = now  # type: ignore

    correct_count = int(stat.correct_count or 0)
    error_count = int(stat.error_count or 0)
    ef = _ease_factor(correct_count, correct_count + error_count)

    current_stage = int(stat.mastery_level or 0)

    if correct:
        new_stage = min(3, current_stage + 1)
        interval_days = ceil(_STAGE_INTERVALS[new_stage] * ef)
    else:
        # SM-2: failed card drops one stage and is reviewed after 1 day
        new_stage = max(0, current_stage - 1)
        interval_days = 1

    stat.mastery_level = new_stage  # type: ignore
    stat.next_review_at = now + timedelta(days=interval_days)  # type: ignore
