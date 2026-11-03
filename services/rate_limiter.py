"""Rate limiting for /api/auth/* with counters stored in PostgreSQL (ADR-1).

Two layers, counted over a sliding WINDOW:
  * (IP, account) - LIMIT_PAIR failures -> 429 (guessing one account from one source)
  * IP            - LIMIT_IP failures   -> 429 (many accounts from one source)
The block is temporary: it lifts as soon as the failures leave the window.
Blocked requests are not recorded, so an attacker cannot extend the block.
"""
import logging
import math
import os
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from db.models import AuthAttempt

logger = logging.getLogger("signwave")

WINDOW = timedelta(minutes=15)
LIMIT_PAIR = 5
LIMIT_IP = 20
RETENTION = timedelta(days=1)

# Number of reverse proxies in front of the app that append to X-Forwarded-For.
# 0 = trust only the socket address (X-Forwarded-For can be spoofed by clients).
TRUSTED_PROXY_COUNT = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))


def client_ip(request: Request) -> str:
    if TRUSTED_PROXY_COUNT > 0:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hops) >= TRUSTED_PROXY_COUNT:
            return hops[-TRUSTED_PROXY_COUNT]
    return request.client.host if request.client else "unknown"


def normalize_account(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value or None


def retry_after_seconds(failures: list[datetime], limit: int, now: datetime) -> int:
    """Seconds until fewer than `limit` of the (ascending) failures remain in the window; 0 if not blocked."""
    if len(failures) < limit:
        return 0
    unblock_at = failures[len(failures) - limit] + WINDOW
    return max(1, math.ceil((unblock_at - now).total_seconds()))


def evaluate(ip_failures: list[datetime], pair_failures: list[datetime], now: datetime) -> int:
    return max(
        retry_after_seconds(ip_failures, LIMIT_IP, now),
        retry_after_seconds(pair_failures, LIMIT_PAIR, now),
    )


def _failures(db: Session, kind: str, since: datetime, ip: str, account: str | None = None) -> list[datetime]:
    q = db.query(AuthAttempt.created_at).filter(
        AuthAttempt.kind == kind,
        AuthAttempt.ip == ip,
        AuthAttempt.success.is_(False),
        AuthAttempt.created_at >= since,
    )
    if account is not None:
        q = q.filter(AuthAttempt.account == account)
    return [row[0] for row in q.order_by(AuthAttempt.created_at).all()]


def _last_success(db: Session, kind: str, ip: str, account: str, since: datetime) -> datetime | None:
    row = (
        db.query(AuthAttempt.created_at)
        .filter(
            AuthAttempt.kind == kind,
            AuthAttempt.ip == ip,
            AuthAttempt.account == account,
            AuthAttempt.success.is_(True),
            AuthAttempt.created_at >= since,
        )
        .order_by(AuthAttempt.created_at.desc())
        .first()
    )
    return row[0] if row else None


def check(db: Session, kind: str, ip: str, account: str | None) -> None:
    """Raise 429 with Retry-After if the request is over a limit. Call before touching user data."""
    now = datetime.utcnow()
    since = now - WINDOW

    ip_failures = _failures(db, kind, since, ip)
    pair_failures: list[datetime] = []
    if account is not None:
        # a successful login from this IP forgives its earlier typos
        last_ok = _last_success(db, kind, ip, account, since)
        pair_failures = _failures(db, kind, last_ok or since, ip, account)

    wait = evaluate(ip_failures, pair_failures, now)
    if wait:
        logger.warning(f"rate limit: kind={kind} ip={ip} account={account} retry_after={wait}s")
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Try again in {math.ceil(wait / 60)} min.",
            headers={"Retry-After": str(wait)},
        )


def record(db: Session, kind: str, ip: str, account: str | None, success: bool) -> None:
    db.add(AuthAttempt(kind=kind, ip=ip, account=account, success=success))
    db.commit()


def purge_old(db: Session) -> int:
    deleted = db.query(AuthAttempt).filter(AuthAttempt.created_at < datetime.utcnow() - RETENTION).delete()
    db.commit()
    return deleted
