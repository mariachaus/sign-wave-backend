"""Unit tests for services.rate_limiter (decision logic; the DB helpers are stubbed)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from services import rate_limiter as rl

_utcnow = rl._utcnow

NOW = datetime(2026, 11, 2, 12, 0, 0)


def _fails(n, age_minutes=1):
    """n failures, the oldest `age_minutes` old, one per second."""
    start = NOW - timedelta(minutes=age_minutes)
    return [start + timedelta(seconds=i) for i in range(n)]


def test_below_limits_is_not_blocked():
    assert rl.evaluate(_fails(19), _fails(4), NOW) == 0


def test_pair_limit_blocks_with_retry_after():
    wait = rl.evaluate([], _fails(5, age_minutes=1), NOW)
    assert wait == 14 * 60  # oldest failure leaves the 15 min window in 14 min


def test_retry_after_waits_for_enough_failures_to_expire():
    # 7 failures, limit 5: blocked until only 4 remain, i.e. until the 3rd oldest expires
    failures = _fails(7, age_minutes=10)
    wait = rl.retry_after_seconds(failures, rl.LIMIT_PAIR, NOW)
    expected = (failures[2] + rl.WINDOW - NOW).total_seconds()
    assert wait == expected


def test_ip_limit_blocks_across_accounts():
    assert rl.evaluate(_fails(20), [], NOW) > 0


def test_normalize_account():
    assert rl.normalize_account("  Alice ") == "alice"
    assert rl.normalize_account("") is None
    assert rl.normalize_account(None) is None


def _request(headers=None, host="10.0.0.1"):
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=host))


def test_client_ip_ignores_forwarded_for_without_trusted_proxy(monkeypatch):
    monkeypatch.setattr(rl, "TRUSTED_PROXY_COUNT", 0)
    assert rl.client_ip(_request({"x-forwarded-for": "6.6.6.6"})) == "10.0.0.1"


def test_client_ip_uses_address_added_by_trusted_proxy(monkeypatch):
    monkeypatch.setattr(rl, "TRUSTED_PROXY_COUNT", 1)
    # the client may prepend fake hops; the proxy appends the real peer last
    assert rl.client_ip(_request({"x-forwarded-for": "6.6.6.6, 1.2.3.4"})) == "1.2.3.4"


def test_client_ip_falls_back_when_header_missing(monkeypatch):
    monkeypatch.setattr(rl, "TRUSTED_PROXY_COUNT", 1)
    assert rl.client_ip(_request()) == "10.0.0.1"


@pytest.fixture
def stub_db(monkeypatch):
    """Stub the DB helpers; the failure lists honour `since` like the SQL filter does."""
    state = SimpleNamespace(ip=[], pair=[], last_ok=None)

    def failures(db, kind, since, ip, account=None, exclude_id=None):
        source = state.pair if account is not None else state.ip
        return [t for t in source if t >= since]

    monkeypatch.setattr(rl, "_failures", failures)
    monkeypatch.setattr(rl, "_last_success", lambda db, kind, ip, account, since: state.last_ok)
    return state


def _recent(n, minutes_ago=1):
    return [_utcnow() - timedelta(minutes=minutes_ago)] * n


def test_begin_raises_429_with_retry_after_and_drops_the_attempt(stub_db):
    stub_db.pair = _recent(5)
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        rl.begin(db, "login", "1.1.1.1", "alice")
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) > 0
    db.delete.assert_called_once()  # a blocked attempt must not extend the block


def test_begin_keeps_the_attempt_below_the_limit(stub_db):
    stub_db.pair = _recent(4)
    db = MagicMock()
    attempt = rl.begin(db, "login", "1.1.1.1", "alice")
    assert attempt is db.add.call_args.args[0]
    db.delete.assert_not_called()


def test_begin_commits_the_attempt_before_counting(stub_db, monkeypatch):
    # concurrent requests can only see each other if the row is committed before the count
    events = []
    counted = rl._failures
    monkeypatch.setattr(rl, "_failures", lambda *a, **k: (events.append("count"), counted(*a, **k))[1])
    db = MagicMock()
    db.commit.side_effect = lambda: events.append("commit")

    rl.begin(db, "login", "1.1.1.1", "alice")

    assert events[0] == "commit" and "count" in events


def test_begin_blocks_on_ip_limit_across_accounts(stub_db):
    stub_db.ip = _recent(20)
    with pytest.raises(HTTPException):
        rl.begin(MagicMock(), "login", "1.1.1.1", "someone-else")


def test_successful_login_forgives_earlier_failures(stub_db):
    stub_db.pair = _recent(5, minutes_ago=10)
    # the real helper reads failures newer than last_ok; the stub does the same through `since`
    stub_db.last_ok = _utcnow() - timedelta(minutes=2)
    rl.begin(MagicMock(), "login", "1.1.1.1", "alice")


def test_failures_after_the_last_success_still_count(stub_db):
    stub_db.last_ok = _utcnow() - timedelta(minutes=5)
    stub_db.pair = _recent(5, minutes_ago=1)
    with pytest.raises(HTTPException):
        rl.begin(MagicMock(), "login", "1.1.1.1", "alice")


def test_begin_without_account_counts_only_the_ip(stub_db):
    stub_db.pair = _recent(50)  # must be ignored: no account
    rl.begin(MagicMock(), "google", "1.1.1.1", None)


def test_succeed_marks_the_attempt_as_success():
    attempt, db = SimpleNamespace(success=False), MagicMock()
    rl.succeed(db, attempt)
    assert attempt.success is True
    db.commit.assert_called_once()
