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
    monkeypatch.delenv("TWILIO_CALL_RECORDING_ENABLED", raising=False)
    body = build_stream_response("example.ngrok.app")
    assert 'recordingChannels="dual"' in body
