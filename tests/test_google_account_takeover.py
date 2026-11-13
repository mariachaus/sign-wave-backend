import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from routes import auth
from schemas import GoogleLoginRequest, LoginRequest, RegisterRequest

_ROOT = Path(__file__).resolve().parent.parent

EMAIL = "victim@gmail.com"
ATTACKER_USERNAME = "attacker"
ATTACKER_PASSWORD = "Attacker123!"


def _load(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, _ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _GoogleResponse:
    status_code = 200

    def json(self):
        return {"sub": "google-victim-1", "email": EMAIL, "email_verified": True, "name": "Victim"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    models = _load("real_models", "db/models.py")
    deps = _load("real_dependencies", "core/dependencies.py")
    monkeypatch.setattr(deps, "User", models.User)
    for name in ("User", "UserSetting", "UserStreak", "UserAchievement", "Achievement",
                 "PasswordResetToken", "EmailVerificationToken"):
        monkeypatch.setattr(auth, name, getattr(models, name))

    monkeypatch.setattr(auth.rate_limiter, "client_ip", lambda request: "1.1.1.1")
    monkeypatch.setattr(auth.rate_limiter, "begin", lambda *args: None)
    monkeypatch.setattr(auth.rate_limiter, "succeed", lambda *args: None)
    monkeypatch.setattr(auth, "send_email_verification", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth.http_requests, "get", lambda *args, **kwargs: _GoogleResponse())

    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    yield SimpleNamespace(db=db, models=models, deps=deps)
    db.close()
    engine.dispose()


def _register(env):
    auth.register(RegisterRequest(username=ATTACKER_USERNAME, email=EMAIL, password=ATTACKER_PASSWORD),
                  request=None, db=env.db)


def _login(env, username=ATTACKER_USERNAME, password=ATTACKER_PASSWORD):
    return auth.login(LoginRequest(username=username, password=password), request=None, db=env.db)


def _google_login(env):
    return auth.google_login(GoogleLoginRequest(access_token="google-token"), request=None, db=env.db)


def _authorize(env, token):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return env.deps.get_current_user_id(credentials, env.db)


def _user(env):
    env.db.expire_all()
    return env.db.query(env.models.User).filter_by(email=EMAIL).one()


def test_attacker_password_rejected_after_owner_signs_in_with_google(env):
    _register(env)                                  # 1. attacker registers, email stays unconfirmed
    attacker_token = _login(env)["access_token"]    # 2. attacker has a session before the owner shows up

    owner = _google_login(env)                      # 3. owner signs in with Google

    with pytest.raises(HTTPException) as exc:       # 5. attacker's password no longer works
        _login(env)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:       # the attacker's earlier session is revoked
        _authorize(env, attacker_token)
    assert exc.value.status_code == 401

    assert _authorize(env, owner["access_token"]) == owner["user_id"]
    user = _user(env)
    assert user.password_hash is None
    assert user.google_id == "google-victim-1"
    assert user.is_email_verified is True
    assert env.db.query(env.models.EmailVerificationToken).count() == 0


def test_verified_account_keeps_password_and_sessions_when_linking_google(env):
    _register(env)
    user = _user(env)
    user.is_email_verified = True
    env.db.commit()
    password_token = _login(env)["access_token"]

    _google_login(env)

    assert _authorize(env, password_token) == user.id
    assert _login(env)["user_id"] == user.id
    assert _user(env).google_id == "google-victim-1"


def test_google_only_account_cannot_log_in_with_a_password(env):
    owner = _google_login(env)
    username = _user(env).username

    with pytest.raises(HTTPException) as exc:
        _login(env, username=username, password="None")
    assert exc.value.status_code == 401
    assert _authorize(env, owner["access_token"]) == owner["user_id"]


def test_token_without_version_claim_stays_valid(env):
    from jose import jwt
    from services.auth_utils import ALGORITHM, SECRET_KEY

    owner = _google_login(env)
    legacy = jwt.encode({"sub": str(owner["user_id"])}, SECRET_KEY, algorithm=ALGORITHM)

    assert _authorize(env, legacy) == owner["user_id"]
