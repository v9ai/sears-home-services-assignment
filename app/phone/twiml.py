"""TwiML for the inbound voice webhook.

Answers every call with ``<Connect><Stream url="wss://{PUBLIC_HOST}/ws/twilio"/></Connect>``
(requirements.md "Included"), forwarding ``From``/``To``/``CallSid`` as ``<Parameter>``
children so the Media Streams ``start`` event's ``customParameters`` carries the caller
number through to the bridge without a separate Twilio REST lookup.

Unless disabled, a ``<Start><Recording></Start>`` precedes the ``<Connect>`` -- ``<Start>``
verbs run asynchronously and don't block, so Twilio records the whole call (both legs)
in parallel with the bidirectional Media Stream. This is what makes a call show up in
Twilio's own Recordings resource (``client.recordings.list(call_sid=...)``), independent
of the app's own per-turn WAV/MP3 capture (``app/recordings/routes.py``).
"""

from __future__ import annotations

import logging
import os

from twilio.twiml.voice_response import Connect, Start, VoiceResponse

logger = logging.getLogger("app.phone")

DEFAULT_STREAM_PATH = "/ws/twilio"


def _recording_enabled() -> bool:
    return os.environ.get("TWILIO_CALL_RECORDING_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _strip_scheme(host: str) -> str:
    host = host.strip()
    for prefix in ("wss://", "ws://", "https://", "http://"):
        if host.startswith(prefix):
            return host[len(prefix) :]
    return host


def build_stream_response(
    public_host: str,
    *,
    path: str = DEFAULT_STREAM_PATH,
    call_sid: str | None = None,
    from_number: str | None = None,
    to_number: str | None = None,
) -> str:
    """Build the ``<Connect><Stream>`` TwiML document as a string.

    ``public_host`` may be given with or without a scheme (``PUBLIC_HOST`` is stored
    bare in ``.env``); the stream URL is always ``wss://``.
    """
    host = _strip_scheme(public_host).rstrip("/")
    if not host:
        logger.error(
            "twiml_build_empty_public_host call=%s raw_public_host=%r",
            call_sid,
            public_host,
        )
        raise ValueError("public_host must not be empty")
    stream_url = f"wss://{host}{path}"
    recording_enabled = _recording_enabled()

    logger.debug(
        "twiml_build call=%s stream_url=%s recording_enabled=%s from=%s to=%s",
        call_sid,
        stream_url,
        recording_enabled,
        from_number,
        to_number,
    )

    response = VoiceResponse()
    if recording_enabled:
        start = Start()
        start.recording(channels="dual")
        response.append(start)
    connect = Connect()
    stream = connect.stream(url=stream_url)
    if call_sid:
        stream.parameter(name="CallSid", value=call_sid)
    if from_number:
        stream.parameter(name="From", value=from_number)
    if to_number:
        stream.parameter(name="To", value=to_number)
    response.append(connect)
    body = str(response)
    logger.debug("twiml_build_done call=%s body=%s", call_sid, body)
    return body
