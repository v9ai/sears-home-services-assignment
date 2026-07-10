"""Twilio Media Streams wire-protocol tests for `SafeTwilioFrameSerializer`.

`tests/voice/test_serializer.py` pins the *defensive* behavior (malformed frames,
counters, the storm tripwire). This file pins the *protocol* itself — the exact JSON
envelopes on the wire and the mulaw payload integrity in both directions — so a Pipecat
upgrade that changes the Twilio Media Streams framing fails loudly here rather than only
on a live PSTN call:

- outbound: an `OutputAudioRawFrame` serializes to `{"event": "media", "streamSid", "media":
  {"payload": <b64 mulaw>}}`; an `InterruptionFrame` to `{"event": "clear", "streamSid"}`.
- inbound: a `media` event deserializes to an `InputAudioRawFrame` whose PCM is the 8 kHz
  mulaw payload expanded 2×; a `dtmf` event to an `InputDTMFFrame`; `mark`/`stop`/`connected`
  to `None` (no frame, no raise).
- integrity: 8 kHz mulaw survives a deserialize→serialize round trip byte-for-byte.

All hermetic — the serializer is built with `auto_hang_up=False` and empty creds, exactly
as the stutter bench builds it, so nothing touches the network.
"""

from __future__ import annotations

import base64
import json

import pytest

pytest.importorskip("pipecat.serializers.twilio")

from pipecat.frames.frames import (  # noqa: E402
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    StartFrame,
)
from pipecat.serializers.twilio import TwilioFrameSerializer  # noqa: E402

from app.voice.serializer import SafeTwilioFrameSerializer  # noqa: E402

STREAM_SID = "MZprotocol"


async def _serializer() -> SafeTwilioFrameSerializer:
    """8 kHz-configured serializer with auto-hangup off (no creds needed)."""
    serializer = SafeTwilioFrameSerializer(
        stream_sid=STREAM_SID,
        call_sid=None,
        account_sid="",
        auth_token="",
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )
    await serializer.setup(StartFrame(audio_in_sample_rate=8000, audio_out_sample_rate=8000))
    return serializer


def _media_event(mulaw: bytes) -> str:
    return json.dumps(
        {
            "event": "media",
            "streamSid": STREAM_SID,
            "media": {"payload": base64.b64encode(mulaw).decode()},
        }
    )


# --- outbound: bot audio + barge-in clear -----------------------------------------------


async def test_outbound_media_envelope_and_payload_length():
    """One 20 ms 8 kHz PCM16 frame (320 bytes) serializes to a Twilio `media` message whose
    base64 payload decodes to 160 mulaw bytes (2:1 PCM->mulaw)."""
    serializer = await _serializer()
    pcm = b"\x00\x00" * 160  # 320 bytes = 160 samples = 20 ms @ 8 kHz

    out = await serializer.serialize(
        OutputAudioRawFrame(audio=pcm, sample_rate=8000, num_channels=1)
    )

    message = json.loads(out)
    assert message["event"] == "media"
    assert message["streamSid"] == STREAM_SID
    payload = base64.b64decode(message["media"]["payload"])
    assert len(payload) == 160  # PCM16 halves into mulaw
    assert serializer.outbound_frames == 1
    assert serializer.bargein_clears == 0


async def test_outbound_interruption_serializes_to_clear():
    """A barge-in is an `InterruptionFrame` -> Twilio `clear`, which flushes the audio Twilio
    has already buffered for the caller (the cancel-TTS-playback mechanism)."""
    serializer = await _serializer()

    out = await serializer.serialize(InterruptionFrame())

    assert json.loads(out) == {"event": "clear", "streamSid": STREAM_SID}
    assert serializer.bargein_clears == 1


async def test_outbound_mulaw_payload_preserves_pcm_content():
    """Payload integrity: distinct PCM in -> distinct mulaw out (not silence/zeros)."""
    serializer = await _serializer()
    # A ramp: guarantees non-trivial, non-constant mulaw so a broken encoder can't pass.
    pcm = bytes(range(256)) * 2  # 512 bytes = 256 samples

    out = await serializer.serialize(
        OutputAudioRawFrame(audio=pcm, sample_rate=8000, num_channels=1)
    )

    payload = base64.b64decode(json.loads(out)["media"]["payload"])
    assert len(payload) == 256
    assert len(set(payload)) > 1  # genuinely varying audio, not a constant


# --- inbound: caller audio + DTMF -------------------------------------------------------


async def test_inbound_media_deserializes_to_pcm_frame():
    """A Twilio `media` event -> `InputAudioRawFrame`; the 8 kHz mulaw payload expands 2× into
    PCM16 the pipeline can consume."""
    serializer = await _serializer()
    mulaw = bytes(range(0, 160))

    frame = await serializer.deserialize(_media_event(mulaw))

    assert isinstance(frame, InputAudioRawFrame)
    assert frame.sample_rate == 8000
    assert len(frame.audio) == 2 * len(mulaw)  # mulaw -> PCM16
    assert serializer.inbound_frames == 1
    assert serializer.malformed_frames == 0


async def test_mulaw_survives_deserialize_serialize_round_trip():
    """8 kHz mulaw -> PCM (inbound) -> mulaw (outbound) is byte-for-byte identity: the codec
    conversion the transport does on every frame is lossless, so re-encoded echo audio can't
    silently drift."""
    serializer = await _serializer()
    mulaw = bytes(range(0, 255, 7))

    frame = await serializer.deserialize(_media_event(mulaw))
    out = await serializer.serialize(
        OutputAudioRawFrame(audio=frame.audio, sample_rate=8000, num_channels=1)
    )

    assert base64.b64decode(json.loads(out)["media"]["payload"]) == mulaw


async def test_inbound_dtmf_deserializes_to_keypad_frame():
    serializer = await _serializer()

    frame = await serializer.deserialize(
        json.dumps({"event": "dtmf", "streamSid": STREAM_SID, "dtmf": {"digit": "5"}})
    )

    assert isinstance(frame, InputDTMFFrame)
    assert frame.button.value == "5"


async def test_inbound_bad_dtmf_digit_is_ignored():
    """A non-keypad `digit` yields no frame (and no raise) — the same graceful path as an
    unknown event type, so a garbled DTMF can't end the receive loop."""
    serializer = await _serializer()

    frame = await serializer.deserialize(
        json.dumps({"event": "dtmf", "streamSid": STREAM_SID, "dtmf": {"digit": "X"}})
    )

    assert frame is None
    assert serializer.malformed_frames == 0  # a handled event, not a malformed frame


# --- lifecycle events that carry no frame ----------------------------------------------


@pytest.mark.parametrize(
    "event",
    [
        {"event": "mark", "streamSid": STREAM_SID, "mark": {"name": "m1"}},
        {"event": "stop", "streamSid": STREAM_SID},
        {"event": "connected", "protocol": "Call", "version": "1.0.0"},
    ],
)
async def test_lifecycle_events_deserialize_to_none_without_raising(event):
    serializer = await _serializer()

    assert await serializer.deserialize(json.dumps(event)) is None
    assert serializer.inbound_frames == 1
    assert serializer.malformed_frames == 0


async def test_full_inbound_sequence_counts_every_message_once():
    """A realistic caller-side event stream (media, dtmf, mark, one malformed) — every inbound
    message passes `deserialize` exactly once, so the media counters in `twilio.call.summary`
    stay accurate."""
    serializer = await _serializer()

    await serializer.deserialize(_media_event(bytes(160)))
    await serializer.deserialize(_media_event(bytes(160)))
    await serializer.deserialize(
        json.dumps({"event": "dtmf", "streamSid": STREAM_SID, "dtmf": {"digit": "1"}})
    )
    await serializer.deserialize(json.dumps({"event": "mark", "streamSid": STREAM_SID}))
    await serializer.deserialize("not json at all")  # malformed

    assert serializer.inbound_frames == 5
    assert serializer.malformed_frames == 1
