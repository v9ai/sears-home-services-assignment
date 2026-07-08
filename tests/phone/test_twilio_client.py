"""app/phone/twilio_client.py -- config-error behavior (mirrors test_webhook.py's
signature-config-error convention)."""

from __future__ import annotations

import pytest

from app.phone.twilio_client import TwilioConfigError, get_twilio_client


def test_missing_credentials_raise_config_error(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    with pytest.raises(TwilioConfigError):
        get_twilio_client()


def test_missing_account_sid_only_raises_config_error(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token")
    with pytest.raises(TwilioConfigError):
        get_twilio_client()


def test_configured_credentials_return_client(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token_test")
    client = get_twilio_client()
    assert client.username == "AC_test"
