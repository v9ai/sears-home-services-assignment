"""TwiML for the inbound voice webhook.

Answers every call with ``<Connect><Stream url="wss://{PUBLIC_HOST}/ws/twilio"/></Connect>``
(requirements.md "Included"), forwarding ``From``/``To``/``CallSid`` as ``<Parameter>``
children so the Media Streams ``start`` event's ``customParameters`` carries the caller
number through to the bridge without a separate Twilio REST lookup.
"""

from __future__ import annotations

from twilio.twiml.voice_response import Connect, VoiceResponse

DEFAULT_STREAM_PATH = "/ws/twilio"


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
        raise ValueError("public_host must not be empty")
    stream_url = f"wss://{host}{path}"

    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=stream_url)
    if call_sid:
        stream.parameter(name="CallSid", value=call_sid)
    if from_number:
        stream.parameter(name="From", value=from_number)
    if to_number:
        stream.parameter(name="To", value=to_number)
    response.append(connect)
    return str(response)
