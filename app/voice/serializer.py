"""A defensive `TwilioFrameSerializer` that survives malformed Media Streams JSON.

`TwilioFrameSerializer.deserialize()` already returns ``None`` gracefully for unknown
Twilio event types and bad DTMF digits, but raises ``KeyError``/``json.JSONDecodeError``
on malformed JSON or a ``"media"`` event missing its ``media``/``payload`` keys.
``FastAPIWebsocketTransport``'s receive loop only catches that at the *outer* loop
level, so one malformed inbound frame ends the whole receive loop (and with it, the
call's ability to hear the caller) rather than just skipping that one message. Same bug
class as the malformed-media-frame crash fixed pre-port (commit 70f32c2) in the deleted
`app/phone/` bridge, reintroduced here by relying on Pipecat's default behavior.
"""

from __future__ import annotations

import logging

from pipecat.frames.frames import Frame, InterruptionFrame
from pipecat.serializers.twilio import TwilioFrameSerializer

from app.obs import log_event

logger = logging.getLogger("app.voice.serializer")


class SafeTwilioFrameSerializer(TwilioFrameSerializer):
    """Drop-in `TwilioFrameSerializer` that treats a malformed frame as "ignore this
    message" instead of letting the exception break the transport's receive loop.

    Also the call's wire boundary, so it keeps the aggregate media counters the
    telephony observability spec requires (counts only — never the payloads): each
    inbound WS message and each outbound serialized frame passes here exactly once.
    The counters feed the end-of-call ``twilio.call.summary`` event in ``run_bot``.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.inbound_frames = 0
        self.outbound_frames = 0
        self.malformed_frames = 0
        self.bargein_clears = 0

    async def deserialize(self, data: str | bytes) -> Frame | None:
        self.inbound_frames += 1
        try:
            return await super().deserialize(data)
        except (KeyError, ValueError) as exc:  # ValueError covers json.JSONDecodeError
            self.malformed_frames += 1
            log_event(logger, "voice.malformed_twilio_frame", error=type(exc).__name__)
            return None

    async def serialize(self, frame: Frame) -> str | bytes | None:
        result = await super().serialize(frame)
        if result is not None:
            self.outbound_frames += 1
            if isinstance(frame, InterruptionFrame):
                # Serialized as Twilio's {"event": "clear"} — one flushed reply. A storm
                # of these within single replies is the barge-in echo loop signature
                # (docs/local-twilio-run.md), so the count surfaces in twilio.call.summary.
                self.bargein_clears += 1
        return result
