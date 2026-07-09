"""Regression tests for `SafeTwilioFrameSerializer` (`app/voice/serializer.py`).

`TwilioFrameSerializer.deserialize()` raises uncaught `KeyError`/`json.JSONDecodeError`
on malformed Twilio Media Streams JSON, which `FastAPIWebsocketTransport`'s receive
loop only catches at the outer loop level — ending the whole receive loop (and the
call's ability to hear the caller) on one bad frame. Same bug class fixed pre-port by
commit 70f32c2 in the deleted `app/phone/` bridge, reintroduced by the Pipecat port.
"""

from __future__ import annotations

import logging

import pytest

pipecat_frames = pytest.importorskip("pipecat.frames.frames")

from app.voice.serializer import SafeTwilioFrameSerializer  # noqa: E402


def _serializer() -> SafeTwilioFrameSerializer:
    return SafeTwilioFrameSerializer(
        stream_sid="MZ1", call_sid="CA1", account_sid="AC1", auth_token="tok"
    )


@pytest.mark.parametrize(
    "bad_input",
    [
        "not json",  # json.JSONDecodeError
        "{",  # json.JSONDecodeError
        '{"foo": "bar"}',  # missing "event" key -> KeyError
        '{"event": "media"}',  # missing "media" key -> KeyError
        '{"event": "media", "media": {}}',  # missing "payload" key -> KeyError
    ],
)
async def test_malformed_frame_returns_none_without_raising(bad_input):
    serializer = _serializer()
    assert await serializer.deserialize(bad_input) is None


async def test_malformed_frame_logs_event(caplog):
    serializer = _serializer()
    with caplog.at_level(logging.INFO, logger="app.voice.serializer"):
        await serializer.deserialize("not json")

    assert "event=voice.malformed_twilio_frame" in caplog.text
    assert "error=JSONDecodeError" in caplog.text


async def test_unknown_event_type_still_returns_none_unchanged():
    """Positive control: TwilioFrameSerializer already handles unknown event types
    gracefully (returns None, no exception) — the wrapper must not alter that path."""
    serializer = _serializer()
    assert await serializer.deserialize('{"event": "mark"}') is None


# --- aggregate media counters (telephony plan 5b: counts only, never payloads) --------


async def test_counters_track_inbound_and_malformed_frames():
    serializer = _serializer()
    await serializer.deserialize('{"event": "mark"}')  # inbound, well-formed
    await serializer.deserialize("not json")  # inbound, malformed
    await serializer.deserialize("{")  # inbound, malformed

    assert serializer.inbound_frames == 3
    assert serializer.malformed_frames == 2
    assert serializer.outbound_frames == 0


async def test_counters_track_outbound_frames():
    from pipecat.frames.frames import InterruptionFrame

    serializer = _serializer()
    # An InterruptionFrame serializes to Twilio's "clear" message (the barge-in path).
    result = await serializer.serialize(InterruptionFrame())
    assert result is not None
    assert serializer.outbound_frames == 1


async def test_malformed_frame_log_never_contains_the_payload(caplog):
    """Redaction (requirements: never log raw media payloads): the malformed-frame
    event carries only the exception class, not the offending wire bytes."""
    payload = '{"event": "media", "media": {"BOGUS-PAYLOAD-bytes": "SGVsbG8="}}'
    serializer = _serializer()
    with caplog.at_level(logging.INFO, logger="app.voice.serializer"):
        await serializer.deserialize(payload)
    assert "BOGUS-PAYLOAD" not in caplog.text
    assert "SGVsbG8=" not in caplog.text
