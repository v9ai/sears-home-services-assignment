"""Outbound framing tests (stutter-loop f2, `app.voice.bot._build_transport_params`).

Pipecat's default `audio_out_10ms_chunks=4` sends one 40 ms media message per pace
tick; production pins 2 — the Twilio-idiomatic 20 ms/160-byte µ-law cadence the
pre-port bridge used — for finer pacing granularity. The stutter bench's pacing probe
builds its transport through the SAME `_build_transport_params`, so these tests plus
the probe keep bench and production framing from drifting apart.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pipecat.transports.websocket.fastapi")

from pipecat.serializers.twilio import TwilioFrameSerializer  # noqa: E402

from app.voice.bot import (  # noqa: E402
    VOICE_OUT_10MS_CHUNKS_DEFAULT,
    _build_transport_params,
)
from app.voice.serializer import SafeTwilioFrameSerializer  # noqa: E402


def _serializer() -> SafeTwilioFrameSerializer:
    return SafeTwilioFrameSerializer(
        stream_sid="MZ1",
        call_sid=None,
        account_sid="",
        auth_token="",
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )


def test_default_is_20ms_twilio_framing(monkeypatch):
    monkeypatch.delenv("VOICE_OUT_10MS_CHUNKS", raising=False)
    params = _build_transport_params(_serializer())
    assert VOICE_OUT_10MS_CHUNKS_DEFAULT == 2  # 2 x 10 ms = the Twilio-idiomatic frame
    assert params.audio_out_10ms_chunks == 2


def test_env_override_restores_pipecat_default_framing(monkeypatch):
    """The f2 rollback knob: VOICE_OUT_10MS_CHUNKS=4 = pipecat's 40 ms framing."""
    monkeypatch.setenv("VOICE_OUT_10MS_CHUNKS", "4")
    params = _build_transport_params(_serializer())
    assert params.audio_out_10ms_chunks == 4


def test_telephony_params_preserved(monkeypatch):
    """The framing change must not disturb the rest of the transport contract."""
    monkeypatch.delenv("VOICE_OUT_10MS_CHUNKS", raising=False)
    serializer = _serializer()
    params = _build_transport_params(serializer)
    assert params.audio_in_enabled is True
    assert params.audio_out_enabled is True
    assert params.add_wav_header is False  # raw µ-law for telephony
    assert params.serializer is serializer
