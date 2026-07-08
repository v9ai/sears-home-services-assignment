"""``POST /twilio/voice`` -- the inbound call webhook.

Validates ``X-Twilio-Signature`` against ``TWILIO_AUTH_TOKEN`` and returns TwiML
instructing Twilio to open a bidirectional Media Stream to ``/ws/twilio``. An
unsigned or mis-signed request is rejected with 403 before any app logic runs
(requirements.md Decision 4); a missing/misconfigured Auth Token is a 500 (loud
misconfiguration), never a silent pass-through.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request, Response

from app.phone.signature import SignatureConfigError, validate_request
from app.phone.twiml import build_stream_response

router = APIRouter()


def _webhook_url(request: Request) -> str:
    """The URL Twilio actually signed against.

    Twilio signs the exact URL it POSTed to, which is the public/console-configured
    one (``https://{PUBLIC_HOST}/twilio/voice``) -- not necessarily what a proxy-fronted
    FastAPI process sees on ``request.url`` (scheme/host can be rewritten by an
    intermediary). ``PUBLIC_HOST`` is the source of truth when set; falling back to the
    request's own URL keeps this testable without the env var.
    """
    public_host = os.environ.get("PUBLIC_HOST", "").strip()
    if not public_host:
        return str(request.url)
    host = public_host
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return f"{host.rstrip('/')}{request.url.path}"


@router.post("/twilio/voice")
async def voice_webhook(request: Request) -> Response:
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    signature = request.headers.get("X-Twilio-Signature")
    url = _webhook_url(request)

    try:
        signed = validate_request(url, params, signature)
    except SignatureConfigError:
        return Response(status_code=500, content="TWILIO_AUTH_TOKEN is not configured")

    if not signed:
        return Response(status_code=403, content="invalid signature")

    public_host = os.environ.get("PUBLIC_HOST", "").strip() or request.headers.get("host", "")
    twiml = build_stream_response(
        public_host,
        call_sid=params.get("CallSid"),
        from_number=params.get("From"),
        to_number=params.get("To"),
    )
    return Response(content=twiml, media_type="text/xml")
