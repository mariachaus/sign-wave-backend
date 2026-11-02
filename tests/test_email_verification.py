"""Unit tests for the email verification email."""
import logging

import pytest

from schemas import VerifyEmailRequest
from services import email_service


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(email_service, "_send", lambda to, subject, html: calls.append((to, subject, html)))
    return calls


def test_email_contains_verification_link(monkeypatch, sent):
    monkeypatch.setattr(email_service, "MAIL_FROM", "app@example.com")
    monkeypatch.setattr(email_service, "MAIL_PASSWORD", "secret")
    monkeypatch.setattr(email_service, "APP_URL", "http://localhost:5173")

    email_service.send_email_verification("alice@example.com", "alice", "tok123", lang="en")

    assert len(sent) == 1
    to, subject, html = sent[0]
    assert to == "alice@example.com"
    assert subject == "✉️ Confirm your email for SignWave"
    assert "http://localhost:5173/verify-email?token=tok123" in html


def test_email_uses_ukrainian_translation(monkeypatch, sent):
    monkeypatch.setattr(email_service, "MAIL_FROM", "app@example.com")
    monkeypatch.setattr(email_service, "MAIL_PASSWORD", "secret")

    email_service.send_email_verification("alice@example.com", "alice", "tok123", lang="uk")

    assert sent[0][1] == "✉️ Підтвердь свою пошту в SignWave"


def test_link_logged_when_mail_not_configured(monkeypatch, sent, caplog):
    monkeypatch.setattr(email_service, "MAIL_FROM", "")
    monkeypatch.setattr(email_service, "MAIL_PASSWORD", "")
    monkeypatch.setattr(email_service, "APP_URL", "http://localhost:5173")

    with caplog.at_level(logging.WARNING, logger="signwave"):
        email_service.send_email_verification("alice@example.com", "alice", "tok123")

    assert sent == []
    assert "http://localhost:5173/verify-email?token=tok123" in caplog.text


def test_verify_email_request_requires_token():
    with pytest.raises(Exception):
        VerifyEmailRequest()
