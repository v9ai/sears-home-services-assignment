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

from pipecat.frames.frames import Frame
from pipecat.serializers.twilio import TwilioFrameSerializer

from app.obs import log_event

logger = logging.getLogger("app.voice.serializer")


class SafeTwilioFrameSerializer(TwilioFrameSerializer):
    """Drop-in `TwilioFrameSerializer` that treats a malformed frame as "ignore this
    message" instead of letting the exception break the transport's receive loop."""

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            return await super().deserialize(data)
        except (KeyError, ValueError) as exc:  # ValueError covers json.JSONDecodeError
            log_event(logger, "voice.malformed_twilio_frame", error=type(exc).__name__)
            return None
