"""Unit tests for Pydantic request/response models in schemas.py."""
import pytest
from pydantic import ValidationError

from schemas import (
    RegisterRequest,
    LoginRequest,
    ErrorDetail,
    ResetPasswordRequest,
    ChangePasswordRequest,
    LessonCompleteRequest,
)


class TestRegisterRequest:
    def test_valid_data_accepted(self):
        r = RegisterRequest(username="alice", email="alice@example.com", password="secret123")
        assert r.username == "alice"
        assert r.password == "secret123"

    def test_username_too_short_rejected(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="ab", email="a@b.com", password="secret123")

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="alice", email="not-an-email", password="secret123")

    def test_password_too_short_rejected(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="alice", email="a@b.com", password="short")

    def test_password_too_long_rejected(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="alice", email="a@b.com", password="a1" * 51)

    def test_password_without_digit_rejected(self):
        with pytest.raises(ValidationError, match="digit"):
            RegisterRequest(username="alice", email="a@b.com", password="onlyletters")

    def test_password_without_letter_rejected(self):
        with pytest.raises(ValidationError, match="letter"):
            RegisterRequest(username="alice", email="a@b.com", password="12345678")

    def test_cyrillic_letters_accepted(self):
        r = RegisterRequest(username="alice", email="a@b.com", password="пароль123")
        assert r.password == "пароль123"


class TestLoginRequest:
    def test_valid_data_accepted(self):
        r = LoginRequest(username="alice", password="secret123")
        assert r.username == "alice"

    def test_missing_password_rejected(self):
        with pytest.raises(ValidationError):
            LoginRequest(username="alice")

    def test_missing_username_rejected(self):
        with pytest.raises(ValidationError):
            LoginRequest(password="secret123")


class TestErrorDetail:
    def test_defaults_applied(self):
        e = ErrorDetail(gesture_id=5)
        assert e.gesture_id == 5
        assert e.error_type == "wrong_answer"
        assert e.exercise_type_id is None

    def test_custom_values_stored(self):
        e = ErrorDetail(gesture_id=3, exercise_type_id=2, error_type="hand_not_visible")
        assert e.exercise_type_id == 2
        assert e.error_type == "hand_not_visible"


class TestResetPasswordRequest:
    def test_valid_data_accepted(self):
        r = ResetPasswordRequest(token="abc123", new_password="newpass123")
        assert r.token == "abc123"

    def test_short_password_rejected(self):
        with pytest.raises(ValidationError):
            ResetPasswordRequest(token="abc123", new_password="short")

    def test_password_without_digit_rejected(self):
        with pytest.raises(ValidationError):
            ResetPasswordRequest(token="abc123", new_password="newpassword")


class TestChangePasswordRequest:
    def test_valid_data_accepted(self):
        r = ChangePasswordRequest(old_password="anything", new_password="newpass123")
        assert r.new_password == "newpass123"

    def test_old_password_not_validated(self):
        # old passwords created before the rules were introduced must still be accepted
        r = ChangePasswordRequest(old_password="old", new_password="newpass123")
        assert r.old_password == "old"

    def test_weak_new_password_rejected(self):
        with pytest.raises(ValidationError):
            ChangePasswordRequest(old_password="anything", new_password="12345678")

    def test_empty_new_password_rejected(self):
        with pytest.raises(ValidationError):
            ChangePasswordRequest(old_password="anything", new_password="")


class TestLessonCompleteRequest:
    def test_defaults_applied(self):
        r = LessonCompleteRequest(score=80)
        assert r.score == 80
        assert r.errors == []
        assert r.hearts_remaining == 0

    def test_errors_list_accepted(self):
        r = LessonCompleteRequest(
            score=50,
            errors=[{"gesture_id": 1, "error_type": "wrong_answer"}],
            hearts_remaining=3,
        )
        assert len(r.errors) == 1
        assert r.errors[0].gesture_id == 1
