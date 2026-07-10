"""SMTP backend send() path + backend-selection fallbacks (bugfix-loop T4).

The audit found SmtpEmailBackend's entire send() body unexercised — the one
SMTP test read the constructor and stopped, so the implicit-TLS/STARTTLS
branch, the message build, and failure propagation had zero coverage; the
selection fallback for unknown/mixed-case EMAIL_BACKEND was untested too.
"""

from __future__ import annotations

import aiosmtplib
import pytest

from app.email.backend import (
    CloudflareEmailBackend,
    ConsoleEmailBackend,
    SmtpEmailBackend,
    get_email_backend,
    reset_email_backend,
)

_SMTP_ENV = {
    "SMTP_HOST": "mail.example.com",
    "SMTP_PORT": "465",
    "SMTP_USERNAME": "mailer",
    "SMTP_PASSWORD": "hunter2",
    "EMAIL_FROM": "no-reply@shs.example",
}


@pytest.fixture
def smtp_spy(monkeypatch):
    """Capture the (message, kwargs) aiosmtplib.send receives."""
    calls: list[tuple[object, dict]] = []

    async def fake_send(message, **kwargs):
        calls.append((message, kwargs))

    monkeypatch.setattr(aiosmtplib, "send", fake_send)
    return calls


def _configured_backend(monkeypatch, *, port: str) -> SmtpEmailBackend:
    for key, value in {**_SMTP_ENV, "SMTP_PORT": port}.items():
        monkeypatch.setenv(key, value)
    return SmtpEmailBackend()


async def test_port_465_uses_implicit_tls_and_builds_the_message(monkeypatch, smtp_spy) -> None:
    backend = _configured_backend(monkeypatch, port="465")
    await backend.send("caller@example.com", "Your upload link", "Hello there")

    (message, kwargs) = smtp_spy[0]
    assert kwargs["use_tls"] is True and kwargs["start_tls"] is False
    assert kwargs["hostname"] == "mail.example.com" and kwargs["port"] == 465
    assert kwargs["username"] == "mailer" and kwargs["password"] == "hunter2"
    assert message["From"] == "no-reply@shs.example"
    assert message["To"] == "caller@example.com"
    assert message["Subject"] == "Your upload link"
    assert "Hello there" in message.get_content()


async def test_port_587_negotiates_starttls(monkeypatch, smtp_spy) -> None:
    backend = _configured_backend(monkeypatch, port="587")
    await backend.send("caller@example.com", "s", "b")
    (_, kwargs) = smtp_spy[0]
    assert kwargs["start_tls"] is True and kwargs["use_tls"] is False
    assert kwargs["port"] == 587


async def test_smtp_failure_propagates_to_the_caller(monkeypatch) -> None:
    backend = _configured_backend(monkeypatch, port="587")

    async def boom(message, **kwargs):
        raise aiosmtplib.SMTPException("connection refused")

    monkeypatch.setattr(aiosmtplib, "send", boom)
    with pytest.raises(aiosmtplib.SMTPException, match="connection refused"):
        await backend.send("caller@example.com", "s", "b")


@pytest.fixture
def fresh_selection(monkeypatch):
    reset_email_backend()
    yield monkeypatch
    reset_email_backend()


def test_unknown_email_backend_falls_back_to_console(fresh_selection) -> None:
    fresh_selection.setenv("EMAIL_BACKEND", "sendgrid")
    assert isinstance(get_email_backend(), ConsoleEmailBackend)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("SMTP", SmtpEmailBackend), ("Cloudflare", CloudflareEmailBackend)],
)
def test_backend_selection_is_case_insensitive(fresh_selection, value, expected) -> None:
    fresh_selection.setenv("EMAIL_BACKEND", value)
    assert isinstance(get_email_backend(), expected)
