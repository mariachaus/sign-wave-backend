"""Rate limiter against a real database (SQLite file by default, TEST_DATABASE_URL to use PostgreSQL).

conftest mocks db.models, so the real models are loaded under another name and injected into the limiter.
These tests cover what the stubbed unit tests cannot: the real SQL and the concurrent burst.
"""
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services import rate_limiter as rl

_MODELS = Path(__file__).resolve().parent.parent / "db" / "models.py"


@pytest.fixture
def make_session(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("real_models", _MODELS)
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    monkeypatch.setattr(rl, "AuthAttempt", real.AuthAttempt)

    url = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'rl.db'}"
    kwargs = {"connect_args": {"timeout": 30}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    real.AuthAttempt.__table__.drop(engine, checkfirst=True)
    real.AuthAttempt.__table__.create(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def _try(make_session, ip, account, kind="login"):
    db = make_session()
    try:
        rl.begin(db, kind, ip, account)
        return 200
    except HTTPException as e:
        return e.status_code
    finally:
        db.close()


def test_sixth_failure_is_blocked_and_not_recorded(make_session):
    codes = [_try(make_session, "1.1.1.1", "bob") for _ in range(6)]
    assert codes == [200] * 5 + [429]
    db = make_session()
    assert db.query(rl.AuthAttempt).count() == 5  # the blocked attempt was deleted
    db.close()


def test_other_ip_and_other_account_are_not_blocked(make_session):
    for _ in range(5):
        _try(make_session, "1.1.1.1", "bob")
    assert _try(make_session, "2.2.2.2", "bob") == 200
    assert _try(make_session, "1.1.1.1", "alice") == 200


def test_success_forgives_earlier_failures(make_session):
    for _ in range(4):
        _try(make_session, "1.1.1.1", "bob")
    db = make_session()
    rl.succeed(db, rl.begin(db, "login", "1.1.1.1", "bob"))
    db.close()
    assert [_try(make_session, "1.1.1.1", "bob") for _ in range(5)] == [200] * 5


def test_ip_limit_across_accounts(make_session):
    codes = [_try(make_session, "3.3.3.3", f"user{i}") for i in range(21)]
    assert codes == [200] * 20 + [429]


def test_concurrent_burst_lets_through_at_most_the_limit(make_session):
    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(lambda _: _try(make_session, "4.4.4.4", "bob"), range(40)))
    assert codes.count(200) <= rl.LIMIT_PAIR
    assert codes.count(200) + codes.count(429) == 40
