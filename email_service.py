import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

MAIL_FROM     = os.getenv("MAIL_FROM", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_SERVER   = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT     = int(os.getenv("MAIL_PORT", "587"))
APP_URL       = os.getenv("APP_URL", "http://localhost:5173")

# ── Translations ──────────────────────────────────────────────────────────────

_T = {
    "uk": {
        "unsubscribe":        "Відписатися",
        "unsubscribe_note":   "Ти отримав цей лист тому що увімкнена підписка на розсилку SignWave.",
        "continue_btn":       "Продовжити навчання →",
        "open_btn":           "Відкрити SignWave →",

        "streak_subject":     "🔥 Твоя серія {streak} д. під загрозою!",
        "streak_heading":     "Привіт, {username}! 🔥",
        "streak_body":        "Твоя серія — <strong>{streak} {days_word}</strong>. Сьогодні ти ще не заходив(ла).",
        "streak_cta":         "Зайди та виконай хоча б один урок, щоб не втратити прогрес!",
        "day_1":              "день",
        "day_few":            "дні",
        "day_many":           "днів",

        "weekly_subject":     "📊 Твій тижневий підсумок у SignWave",
        "weekly_heading":     "Підсумок тижня, {username}!",
        "weekly_xp":          "XP зароблено",
        "weekly_lessons":     "Уроків пройдено",
        "weekly_streak":      "Днів поспіль 🔥",

        "reset_subject":      "🔑 Відновлення паролю SignWave",
        "reset_heading":      "Привіт, {username}!",
        "reset_body":         "Ми отримали запит на відновлення паролю для твого акаунту.",
        "reset_btn":          "Відновити пароль →",
        "reset_note":         "Посилання дійсне 1 годину. Якщо ти не надсилав(ла) цей запит — просто проігноруй цей лист.",
    },
    "en": {
        "unsubscribe":        "Unsubscribe",
        "unsubscribe_note":   "You received this email because email notifications are enabled in your SignWave account.",
        "continue_btn":       "Continue learning →",
        "open_btn":           "Open SignWave →",

        "streak_subject":     "🔥 Your {streak}-day streak is at risk!",
        "streak_heading":     "Hey, {username}! 🔥",
        "streak_body":        "Your current streak is <strong>{streak} {days_word}</strong>. You haven't logged in today.",
        "streak_cta":         "Complete at least one lesson to keep your progress!",
        "day_1":              "day",
        "day_few":            "days",
        "day_many":           "days",

        "weekly_subject":     "📊 Your weekly SignWave summary",
        "weekly_heading":     "Weekly summary, {username}!",
        "weekly_xp":          "XP earned",
        "weekly_lessons":     "Lessons completed",
        "weekly_streak":      "Day streak 🔥",

        "reset_subject":      "🔑 SignWave password reset",
        "reset_heading":      "Hey, {username}!",
        "reset_body":         "We received a request to reset the password for your account.",
        "reset_btn":          "Reset password →",
        "reset_note":         "This link is valid for 1 hour. If you didn't request this — just ignore this email.",
    },
}


def _tr(lang: str, key: str, **kwargs) -> str:
    translations = _T.get(lang) or _T["en"]
    template = translations.get(key) or _T["en"].get(key, key)
    return template.format(**kwargs) if kwargs else template


def _days_word(lang: str, n: int) -> str:
    if lang == "uk":
        if n % 10 == 1 and n % 100 != 11:
            return _tr(lang, "day_1")
        if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
            return _tr(lang, "day_few")
        return _tr(lang, "day_many")
    return _tr(lang, "day_1") if n == 1 else _tr(lang, "day_many")


# ── Core send ─────────────────────────────────────────────────────────────────

def _send(to: str, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = MAIL_FROM
    msg["To"]      = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(MAIL_FROM, MAIL_PASSWORD)
        smtp.sendmail(MAIL_FROM, to, msg.as_string())


def _base_template(lang: str, content: str) -> str:
    return f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#1a1a2e;">
      <div style="background:#7c3aed;padding:24px 32px;border-radius:12px 12px 0 0;">
        <h1 style="color:#fff;margin:0;font-size:22px;letter-spacing:-0.5px;">SignWave 🤟</h1>
      </div>
      <div style="background:#f8f8fc;padding:28px 32px;border-radius:0 0 12px 12px;border:1px solid #e5e5f0;">
        {content}
        <hr style="border:none;border-top:1px solid #e5e5f0;margin:24px 0;">
        <p style="font-size:12px;color:#999;margin:0;">
          {_tr(lang, "unsubscribe_note")}<br>
          <a href="{APP_URL}/settings" style="color:#7c3aed;">{_tr(lang, "unsubscribe")}</a>
        </p>
      </div>
    </div>
    """


# ── Public API ────────────────────────────────────────────────────────────────

def send_streak_reminder(to: str, username: str, streak: int, lang: str = "uk") -> None:
    days = _days_word(lang, streak)
    content = f"""
      <h2 style="margin:0 0 12px;">{_tr(lang, "streak_heading", username=username)}</h2>
      <p style="font-size:16px;margin:0 0 8px;">
        {_tr(lang, "streak_body", streak=streak, days_word=days)}
      </p>
      <p style="color:#666;margin:0 0 24px;">{_tr(lang, "streak_cta")}</p>
      <a href="{APP_URL}" style="
        display:inline-block;background:#7c3aed;color:#fff;
        padding:12px 28px;border-radius:8px;text-decoration:none;
        font-weight:600;font-size:15px;">
        {_tr(lang, "continue_btn")}
      </a>
    """
    _send(to, _tr(lang, "streak_subject", streak=streak), _base_template(lang, content))


def send_weekly_summary(to: str, username: str, xp: int, lessons: int, streak: int, lang: str = "uk") -> None:
    content = f"""
      <h2 style="margin:0 0 16px;">{_tr(lang, "weekly_heading", username=username)}</h2>
      <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
        <tr>
          <td style="padding:12px;background:#fff;border:1px solid #e5e5f0;border-radius:8px;text-align:center;width:33%;">
            <div style="font-size:28px;font-weight:700;color:#7c3aed;">{xp}</div>
            <div style="font-size:12px;color:#888;margin-top:4px;">{_tr(lang, "weekly_xp")}</div>
          </td>
          <td style="width:12px;"></td>
          <td style="padding:12px;background:#fff;border:1px solid #e5e5f0;border-radius:8px;text-align:center;width:33%;">
            <div style="font-size:28px;font-weight:700;color:#7c3aed;">{lessons}</div>
            <div style="font-size:12px;color:#888;margin-top:4px;">{_tr(lang, "weekly_lessons")}</div>
          </td>
          <td style="width:12px;"></td>
          <td style="padding:12px;background:#fff;border:1px solid #e5e5f0;border-radius:8px;text-align:center;width:33%;">
            <div style="font-size:28px;font-weight:700;color:#f97316;">{streak}</div>
            <div style="font-size:12px;color:#888;margin-top:4px;">{_tr(lang, "weekly_streak")}</div>
          </td>
        </tr>
      </table>
      <a href="{APP_URL}" style="
        display:inline-block;background:#7c3aed;color:#fff;
        padding:12px 28px;border-radius:8px;text-decoration:none;
        font-weight:600;font-size:15px;">
        {_tr(lang, "open_btn")}
      </a>
    """
    _send(to, _tr(lang, "weekly_subject"), _base_template(lang, content))


def send_password_reset(to: str, username: str, token: str, lang: str = "uk") -> None:
    reset_url = f"{APP_URL}/reset-password?token={token}"
    content = f"""
      <h2 style="margin:0 0 12px;">{_tr(lang, "reset_heading", username=username)}</h2>
      <p style="font-size:16px;margin:0 0 20px;">{_tr(lang, "reset_body")}</p>
      <a href="{reset_url}" style="
        display:inline-block;background:#7c3aed;color:#fff;
        padding:12px 28px;border-radius:8px;text-decoration:none;
        font-weight:600;font-size:15px;">
        {_tr(lang, "reset_btn")}
      </a>
      <p style="font-size:13px;color:#888;margin:20px 0 0;">{_tr(lang, "reset_note")}</p>
    """
    _send(to, _tr(lang, "reset_subject"), _base_template(lang, content))


def send_test_email(to: str, username: str = "User", lang: str = "uk") -> None:
    titles = {"uk": "Тестовий лист SignWave", "en": "SignWave test email"}
    greeting = f"Привіт, {username}! Підключення працює! ✅" if lang == "uk" else f"Hey, {username}! Connection works! ✅"
    content = f"""
      <h2 style="margin:0 0 12px;">{greeting}</h2>
      <p style="color:#444;margin:0 0 20px;">
        {"Це тестовий лист. Якщо ти його бачиш — SMTP налаштовано правильно." if lang == "uk"
         else "This is a test email. If you see it — SMTP is configured correctly."}
      </p>
      <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
        <tr>
          <td style="padding:10px 12px;background:#fff;border:1px solid #e5e5f0;font-size:13px;color:#888;">
            {"Відправник" if lang == "uk" else "From"}
          </td>
          <td style="padding:10px 12px;background:#fff;border:1px solid #e5e5f0;font-size:13px;color:#333;">
            {MAIL_FROM}
          </td>
        </tr>
        <tr>
          <td style="padding:10px 12px;background:#f8f8fc;border:1px solid #e5e5f0;font-size:13px;color:#888;">
            {"Одержувач" if lang == "uk" else "To"}
          </td>
          <td style="padding:10px 12px;background:#f8f8fc;border:1px solid #e5e5f0;font-size:13px;color:#333;">
            {to}
          </td>
        </tr>
        <tr>
          <td style="padding:10px 12px;background:#fff;border:1px solid #e5e5f0;font-size:13px;color:#888;">
            {"Сервер" if lang == "uk" else "Server"}
          </td>
          <td style="padding:10px 12px;background:#fff;border:1px solid #e5e5f0;font-size:13px;color:#333;">
            {MAIL_SERVER}:{MAIL_PORT}
          </td>
        </tr>
        <tr>
          <td style="padding:10px 12px;background:#f8f8fc;border:1px solid #e5e5f0;font-size:13px;color:#888;">
            {"Адреса додатку" if lang == "uk" else "App URL"}
          </td>
          <td style="padding:10px 12px;background:#f8f8fc;border:1px solid #e5e5f0;font-size:13px;color:#333;">
            {APP_URL}
          </td>
        </tr>
      </table>
    """
    _send(to, titles.get(lang, titles["en"]), _base_template(lang, content))
