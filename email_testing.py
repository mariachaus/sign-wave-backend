"""Запусти: python test_email.py"""
from email_service import send_test_email
from database_connection import SessionLocal
from database import User, UserSetting
from dotenv import load_dotenv

load_dotenv()

db = SessionLocal()
try:
    rows = (
        db.query(User, UserSetting)
        .join(UserSetting, UserSetting.user_id == User.id)
        .filter(UserSetting.is_email_notifications_enabled == True)
        .all()
    )

    if not rows:
        print("Немає користувачів з увімкненою підпискою на розсилку.")
    else:
        print(f"Знайдено {len(rows)} користувач(ів). Відправляємо...\n")
        for user, settings in rows:
            try:
                send_test_email(user.email, username=user.username, lang=settings.language)
                print(f"✓ {user.username} <{user.email}> [{settings.language}]")
            except Exception as e:
                print(f"✗ {user.username} <{user.email}>: {e}")
finally:
    db.close()
