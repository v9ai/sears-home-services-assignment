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


async def test_interruption_clear_counts_as_barge_in():
    """Each serialized "clear" is one flushed reply; a storm of them within single
    replies is the barge-in echo-loop signature (docs/local-twilio-run.md), so the
    count feeds `barge_ins` in the `twilio.call.summary` event."""
    from pipecat.frames.frames import InterruptionFrame

    serializer = _serializer()
    assert serializer.bargein_clears == 0
    await serializer.serialize(InterruptionFrame())
    await serializer.serialize(InterruptionFrame())
    assert serializer.bargein_clears == 2
    assert serializer.outbound_frames == 2


async def test_media_frames_do_not_count_as_barge_ins():
    from pipecat.frames.frames import StartFrame, TTSAudioRawFrame

    serializer = _serializer()
    await serializer.setup(StartFrame(audio_in_sample_rate=8000, audio_out_sample_rate=8000))
    result = await serializer.serialize(
        TTSAudioRawFrame(audio=b"\x00\x00" * 160, sample_rate=8000, num_channels=1)
    )
    assert result is not None  # a real "media" message went out...
    assert serializer.outbound_frames == 1
    assert serializer.bargein_clears == 0  # ...but only "clear" counts as a barge-in


# --- barge-in storm tripwire (stutter-loop q3) ----------------------------------------


async def _serialize_media(serializer, count: int) -> None:
    from pipecat.frames.frames import TTSAudioRawFrame

    for _ in range(count):
        await serializer.serialize(
            TTSAudioRawFrame(audio=b"\x00\x00" * 160, sample_rate=8000, num_channels=1)
        )


async def test_rapid_reclear_trips_the_storm_tripwire(caplog):
    """The echo-loop signature: a second clear lands after only a few media frames —
    the reply never got going again before being flushed. Must log voice.bargein.storm
    live (mid-call diagnosability, docs/local-twilio-run.md incident)."""
    from pipecat.frames.frames import InterruptionFrame, StartFrame

    from app.voice.serializer import STORM_CLEAR_WINDOW_FRAMES

    serializer = _serializer()
    await serializer.setup(StartFrame(audio_in_sample_rate=8000, audio_out_sample_rate=8000))

    await serializer.serialize(InterruptionFrame())  # first clear of the call: never rapid
    await _serialize_media(serializer, STORM_CLEAR_WINDOW_FRAMES - 1)
    with caplog.at_level(logging.INFO, logger="app.voice.serializer"):
        await serializer.serialize(InterruptionFrame())  # rapid re-clear -> storm

    assert serializer.bargein_clears == 2
    assert serializer.storm_rapid_clears == 1
    assert "event=voice.bargein.storm" in caplog.text
    assert "rapid_clears=1" in caplog.text


async def test_spaced_clears_do_not_trip_the_storm_tripwire(caplog):
    """Two genuine barge-ins separated by a healthy stretch of reply audio are normal
    turn-taking, not a storm."""
    from pipecat.frames.frames import InterruptionFrame, StartFrame

    from app.voice.serializer import STORM_CLEAR_WINDOW_FRAMES

    serializer = _serializer()
    await serializer.setup(StartFrame(audio_in_sample_rate=8000, audio_out_sample_rate=8000))

    await serializer.serialize(InterruptionFrame())
    await _serialize_media(serializer, STORM_CLEAR_WINDOW_FRAMES)
    with caplog.at_level(logging.INFO, logger="app.voice.serializer"):
        await serializer.serialize(InterruptionFrame())

    assert serializer.bargein_clears == 2
    assert serializer.storm_rapid_clears == 0
    assert "voice.bargein.storm" not in caplog.text


async def test_first_clear_of_the_call_is_never_a_storm(caplog):
    from pipecat.frames.frames import InterruptionFrame, StartFrame

    serializer = _serializer()
    await serializer.setup(StartFrame(audio_in_sample_rate=8000, audio_out_sample_rate=8000))
    await _serialize_media(serializer, 3)
    with caplog.at_level(logging.INFO, logger="app.voice.serializer"):
        await serializer.serialize(InterruptionFrame())

    assert serializer.storm_rapid_clears == 0
    assert "voice.bargein.storm" not in caplog.text


async def test_malformed_frame_log_never_contains_the_payload(caplog):
    """Redaction (requirements: never log raw media payloads): the malformed-frame
    event carries only the exception class, not the offending wire bytes."""
    payload = '{"event": "media", "media": {"BOGUS-PAYLOAD-bytes": "SGVsbG8="}}'
    serializer = _serializer()
    with caplog.at_level(logging.INFO, logger="app.voice.serializer"):
        await serializer.deserialize(payload)
    assert "BOGUS-PAYLOAD" not in caplog.text
    assert "SGVsbG8=" not in caplog.text
