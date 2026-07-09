"""Offline units for the Twilio CLI debug toolkit (twilio-cli-debug validation.md).

No Twilio API calls: the twilio-cli wrapper is spied/monkeypatched, ngrok resolution
runs against fixture JSON, and simulate's signing round-trips through the app's own
``app/phone/signature.validate_request``.
"""

from __future__ import annotations

import argparse

import pytest

from app.phone.signature import validate_request
from scripts import twilio_debug


@pytest.fixture(autouse=True)
def _auth_token(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-auth-token-0123456789abcdef")


# --- simulate signing round-trip ---------------------------------------------------


def test_simulate_signature_accepted_by_app_validator(monkeypatch):
    monkeypatch.delenv("PUBLIC_HOST", raising=False)
    form = twilio_debug.build_simulate_form()
    url = twilio_debug.signing_url()
    signature = twilio_debug.compute_signature(url, form)
    assert url == "http://localhost:8000/twilio/voice"
    assert validate_request(url, form, signature) is True


def test_simulate_signs_against_public_host_when_set(monkeypatch):
    # The PUBLIC_HOST-differs-from-request-host case: Twilio signs the public URL,
    # not the URL the local process sees (app/phone/webhook.py::_webhook_url).
    monkeypatch.setenv("PUBLIC_HOST", "example.ngrok.app")
    form = twilio_debug.build_simulate_form()
    url = twilio_debug.signing_url()
    signature = twilio_debug.compute_signature(url, form)
    assert url == "https://example.ngrok.app/twilio/voice"
    assert validate_request(url, form, signature) is True
    # A signature computed for the local URL must NOT validate against the public one.
    local_signature = twilio_debug.compute_signature("http://localhost:8000/twilio/voice", form)
    assert validate_request(url, form, local_signature) is False


# --- ngrok tunnel resolution --------------------------------------------------------

_TUNNELS_FIXTURE = {
    "tunnels": [
        {"public_url": "http://abc123.ngrok.app", "proto": "http"},
        {"public_url": "https://abc123.ngrok.app", "proto": "https"},
    ]
}


def test_resolve_ngrok_url_prefers_https():
    assert twilio_debug.resolve_ngrok_url(_TUNNELS_FIXTURE) == "https://abc123.ngrok.app"


def test_resolve_ngrok_url_empty_payload():
    assert twilio_debug.resolve_ngrok_url({"tunnels": []}) is None


def test_derive_endpoints():
    endpoints = twilio_debug.derive_endpoints("https://abc123.ngrok.app/")
    assert endpoints["voice_url"] == "https://abc123.ngrok.app/twilio/voice"
    assert endpoints["stream_url"] == "wss://abc123.ngrok.app/ws/twilio"


# --- wire dry-run guard --------------------------------------------------------------


def _spy_twilio(calls: list[list[str]], voice_url: str = "https://stale.ngrok.app/twilio/voice"):
    def fake_run_twilio(args: list[str]):
        calls.append(args)
        return [{"sid": "PN356e", "phoneNumber": "+13186468479", "voiceUrl": voice_url}]

    return fake_run_twilio


def test_wire_without_yes_never_updates(monkeypatch, capsys):
    calls: list[list[str]] = []
    monkeypatch.setattr(twilio_debug, "run_twilio", _spy_twilio(calls))
    monkeypatch.setattr(twilio_debug, "resolve_public_url", lambda: "https://fresh.ngrok.app")

    exit_code = twilio_debug.cmd_wire(argparse.Namespace(yes=False))

    assert exit_code == 0
    assert all("update" not in " ".join(call) for call in calls)
    out = capsys.readouterr().out
    assert "https://stale.ngrok.app/twilio/voice" in out  # current
    assert "https://fresh.ngrok.app/twilio/voice" in out  # proposed
    assert "dry run" in out


def test_wire_with_yes_updates_the_recorded_sid_only(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        twilio_debug, "run_twilio", _spy_twilio(calls, "https://fresh.ngrok.app/twilio/voice")
    )
    monkeypatch.setattr(twilio_debug, "resolve_public_url", lambda: "https://fresh.ngrok.app")

    exit_code = twilio_debug.cmd_wire(argparse.Namespace(yes=True))

    assert exit_code == 0
    updates = [call for call in calls if call[0].endswith(":update")]
    assert len(updates) == 1
    assert twilio_debug.DEFAULT_NUMBER_SID in updates[0]
    assert "--voice-method" in updates[0] and "POST" in updates[0]


# --- output redaction -----------------------------------------------------------------


def test_redact_scrubs_token_keys_and_numbers(monkeypatch):
    text = "token=test-auth-token-0123456789abcdef key=sk-abcdef1234567890 caller=+13186468479 done"
    redacted = twilio_debug.redact(text)
    assert "test-auth-token-0123456789abcdef" not in redacted
    assert "sk-abcdef1234567890" not in redacted
    assert "+13186468479" not in redacted
    assert "…8479" in redacted


def test_mask_number_last4():
    assert twilio_debug.mask_number("+13186468479") == "…8479"
    assert twilio_debug.mask_number(None) == "?"


def test_calls_output_masks_numbers(monkeypatch, capsys):
    monkeypatch.setattr(
        twilio_debug,
        "run_twilio",
        lambda args: [
            {
                "sid": "CA123",
                "status": "completed",
                "duration": "42",
                "from": "+13125550123",
                "startTime": "2026-07-09",
            }
        ],
    )
    assert twilio_debug.cmd_calls(argparse.Namespace(limit=5)) == 0
    out = capsys.readouterr().out
    assert "+13125550123" not in out
    assert "…0123" in out
