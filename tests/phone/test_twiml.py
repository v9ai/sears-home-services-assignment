"""``<Start><Recording>`` gating in app/phone/twiml.py."""

from __future__ import annotations

from app.phone.twiml import build_stream_response


def test_recording_enabled_by_default(monkeypatch):
    monkeypatch.delenv("TWILIO_CALL_RECORDING_ENABLED", raising=False)
    body = build_stream_response("example.ngrok.app")
    assert "<Start><Recording" in body
    assert body.index("<Start>") < body.index("<Connect>")


def test_recording_can_be_disabled(monkeypatch):
    monkeypatch.setenv("TWILIO_CALL_RECORDING_ENABLED", "false")
    body = build_stream_response("example.ngrok.app")
    assert "<Recording" not in body
    assert "<Connect>" in body


def test_recording_uses_dual_channels(monkeypatch):
    # 2026-07-09 RCA: `recordingChannels` isn't a valid <Recording> attribute (Twilio
    # error 12200 XML validation warning on every call) -- the correct attribute is
    # `channels`, and the SDK kwarg that produces it is `channels=`, not
    # `recording_channels=` (which silently fell into **kwargs and got camelCased).
    monkeypatch.delenv("TWILIO_CALL_RECORDING_ENABLED", raising=False)
    body = build_stream_response("example.ngrok.app")
    assert 'channels="dual"' in body
    assert "recordingChannels" not in body
