"""Webhook signature validation tests (validation.md, requirements.md Decision 4/6).

Signed requests are computed with the same ``twilio.request_validator.RequestValidator``
Twilio itself uses -- these are "recorded signed requests" in spirit (plan.md group 1)
without needing a captured fixture from a live Twilio account.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.phone.webhook import router

TEST_AUTH_TOKEN = "test-auth-token-not-a-secret"  # noqa: S105 -- fixture value, not a real secret


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TEST_AUTH_TOKEN)
    monkeypatch.setenv("PUBLIC_HOST", "example.ngrok.app")
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


FORM = {"CallSid": "CA123", "From": "+15551234567", "To": "+13186468479"}
URL = "https://example.ngrok.app/twilio/voice"


def _signature(form: dict[str, str] = FORM, url: str = URL, token: str = TEST_AUTH_TOKEN) -> str:
    return RequestValidator(token).compute_signature(url, form)


def test_unsigned_request_rejected(client):
    resp = client.post("/twilio/voice", data=FORM)
    assert resp.status_code == 403


def test_mis_signed_request_rejected(client):
    resp = client.post(
        "/twilio/voice", data=FORM, headers={"X-Twilio-Signature": "not-the-real-signature"}
    )
    assert resp.status_code == 403


def test_signed_with_wrong_token_rejected(client):
    bad_sig = _signature(token="a-different-token")
    resp = client.post("/twilio/voice", data=FORM, headers={"X-Twilio-Signature": bad_sig})
    assert resp.status_code == 403


def test_signed_request_returns_stream_twiml(client):
    sig = _signature()
    resp = client.post("/twilio/voice", data=FORM, headers={"X-Twilio-Signature": sig})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/xml")
    body = resp.text
    assert "<Connect>" in body
    assert "wss://example.ngrok.app/ws/twilio" in body
    # Caller metadata is forwarded as <Parameter> for the Media Streams start event.
    assert 'name="From"' in body and "+15551234567" in body
    assert 'name="CallSid"' in body and "CA123" in body


def test_missing_auth_token_is_a_server_error(monkeypatch):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.post("/twilio/voice", data=FORM, headers={"X-Twilio-Signature": "anything"})
    assert resp.status_code == 500
