"""Unit tests for services.rate_limiter (decision logic; the DB helpers are stubbed)."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services import rate_limiter as rl

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
    """Stub the DB helpers: failure lists per scope and the time of the last success."""
    state = SimpleNamespace(ip=[], pair=[], last_ok=None)

    def failures(db, kind, since, ip, account=None):
        return state.pair if account is not None else state.ip

    monkeypatch.setattr(rl, "_failures", failures)
    monkeypatch.setattr(rl, "_last_success", lambda db, kind, ip, account, since: state.last_ok)
    return state


def test_check_raises_429_with_retry_after_header(stub_db):
    stub_db.pair = [datetime.utcnow()] * 5
    with pytest.raises(HTTPException) as exc:
        rl.check(None, "login", "1.1.1.1", "alice")
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) > 0


def test_check_passes_below_limit(stub_db):
    stub_db.pair = [datetime.utcnow()] * 4
    rl.check(None, "login", "1.1.1.1", "alice")
