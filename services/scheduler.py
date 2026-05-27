import logging
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler # type: ignore

from db.connection import SessionLocal
from db.models import User, UserSetting, UserStreak, UserXPLog, UserLesson
from services.email_service import send_streak_reminder, send_weekly_summary

logger = logging.getLogger("signwave")
scheduler = BackgroundScheduler()


def _send_streak_reminders() -> None:
    """Щодня о 19:00 — нагадування тим, хто не заходив сьогодні."""
    db = SessionLocal()
    try:
        today = date.today()
        rows = (
            db.query(User, UserSetting, UserStreak)
            .join(UserSetting, UserSetting.user_id == User.id)
            .join(UserStreak, UserStreak.user_id == User.id)
            .filter(
                UserSetting.is_email_notifications_enabled == True,
                UserStreak.is_current == True,
                UserStreak.streak_length > 0,
            )
            .all()
        )
        sent = 0
        for user, settings, streak in rows:
            last = streak.last_activity_at
            if last is None or last.date() < today:
                try:
                    send_streak_reminder(user.email, user.username, streak.streak_length, lang=settings.language if settings else "uk")
                    sent += 1
                except Exception as e:
                    logger.error(f"streak reminder failed for {user.email}: {e}")
        logger.info(f"streak reminders sent: {sent}/{len(rows)}")
    finally:
        db.close()


def _send_weekly_summaries() -> None:
    """Щопонеділка о 10:00 — підсумок минулого тижня."""
    db = SessionLocal()
    try:
        week_ago = date.today() - timedelta(days=7)
        users_with_settings = (
            db.query(User, UserSetting)
            .join(UserSetting, UserSetting.user_id == User.id)
            .filter(UserSetting.is_email_notifications_enabled == True)
            .all()
        )
        for user, settings in users_with_settings:
            try:
                xp_this_week = (
                    db.query(UserXPLog)
                    .filter(
                        UserXPLog.user_id == user.id,
                        UserXPLog.created_at >= week_ago,
                    )
                    .with_entities(UserXPLog.amount)
                    .all()
                )
                total_xp = sum(r.amount for r in xp_this_week)

                lessons_this_week = (
                    db.query(UserLesson)
                    .filter(
                        UserLesson.user_id == user.id,
                        UserLesson.completed_at >= week_ago,
                        UserLesson.is_completed == True,
                    )
                    .count()
                )

                streak = (
                    db.query(UserStreak)
                    .filter(UserStreak.user_id == user.id, UserStreak.is_current == True)
                    .first()
                )
                current_streak = streak.streak_length if streak else 0

                if total_xp > 0 or lessons_this_week > 0:
                    send_weekly_summary(
                        user.email, user.username,
                        total_xp, lessons_this_week, current_streak, # type: ignore
                        lang=settings.language if settings else "uk"
                    )
            except Exception as e:
                logger.error(f"weekly summary failed for {user.email}: {e}")
        logger.info("weekly summaries done")
    finally:
        db.close()


def start_scheduler() -> None:
    scheduler.add_job(_send_streak_reminders, "cron", hour=19, minute=0, id="streak_reminder")
    scheduler.add_job(_send_weekly_summaries, "cron", day_of_week="mon", hour=10, minute=0, id="weekly_summary")
    scheduler.start()
    logger.info("scheduler started")


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
    logger.info("scheduler stopped")
