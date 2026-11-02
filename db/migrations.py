from sqlalchemy import text

_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_email_verified BOOLEAN NOT NULL DEFAULT FALSE",
    # Google has already verified the email of accounts created or linked through Google
    "UPDATE users SET is_email_verified = TRUE WHERE google_id IS NOT NULL AND is_email_verified = FALSE",
]


def run_migrations(engine) -> None:
    with engine.begin() as conn:
        for statement in _MIGRATIONS:
            conn.execute(text(statement))
