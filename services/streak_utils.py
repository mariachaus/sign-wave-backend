from datetime import datetime, timedelta

def effective_streak_length(streak, now: datetime | None = None) -> int:
    if not streak or not streak.is_current or not streak.last_activity_at:
        return 0
    today = (now or datetime.utcnow()).date()
    gap = (today - streak.last_activity_at.date()).days
    if gap <= 1:
        return streak.streak_length or 0
    if gap == 2 and (streak.freeze_shields_count or 0) > 0:
        return streak.streak_length or 0 
    return 0