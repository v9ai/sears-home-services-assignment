"""``POST /twilio/voice`` -- the inbound call webhook.

Validates ``X-Twilio-Signature`` against ``TWILIO_AUTH_TOKEN`` and returns TwiML
instructing Twilio to open a bidirectional Media Stream to ``/ws/twilio``. An
unsigned or mis-signed request is rejected with 403 before any app logic runs
(requirements.md Decision 4); a missing/misconfigured Auth Token is a 500 (loud
misconfiguration), never a silent pass-through.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter, Request, Response

from app.obs import bind_call_context, log_event
from app.phone.signature import SignatureConfigError, validate_request
from app.phone.twiml import build_stream_response

logger = logging.getLogger("app.phone")

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
    # Every failure branch here is a candidate for Twilio's generic spoken fallback
    # ("We're sorry, an application error has occurred") -- the caller hears nothing
    # useful, so this is the ONLY place that context survives; log liberally. Never
    # log the signature itself or TWILIO_AUTH_TOKEN.
    webhook_started = time.monotonic()
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    signature = request.headers.get("X-Twilio-Signature")
    url = _webhook_url(request)
    call_sid = params.get("CallSid")
    from_number = params.get("From")
    to_number = params.get("To")
    call_status = params.get("CallStatus")
    bind_call_context(call_sid=call_sid)

    logger.info(
        "phone_webhook_received call=%s from=%s to=%s status=%s url=%s has_signature=%s "
        "user_agent=%s",
        call_sid,
        from_number,
        to_number,
        call_status,
        url,
        bool(signature),
        request.headers.get("user-agent"),
    )

    try:
        signed = validate_request(url, params, signature)
    except SignatureConfigError:
        logger.error(
            "phone_webhook_auth_token_missing call=%s from=%s url=%s -- "
            "TWILIO_AUTH_TOKEN is not configured, every inbound call will 500",
            call_sid,
            from_number,
            url,
        )
        log_event(
            logger,
            "twilio.webhook",
            call=call_sid,
            signature_valid=False,
            ms=(time.monotonic() - webhook_started) * 1000,
        )
        return Response(status_code=500, content="TWILIO_AUTH_TOKEN is not configured")

    if not signed:
        logger.warning(
            "phone_webhook_signature_rejected call=%s from=%s to=%s url=%s has_signature=%s "
            "param_keys=%s",
            call_sid,
            from_number,
            to_number,
            url,
            bool(signature),
            sorted(params.keys()),
        )
        log_event(
            logger,
            "twilio.webhook",
            call=call_sid,
            signature_valid=False,
            ms=(time.monotonic() - webhook_started) * 1000,
        )
        return Response(status_code=403, content="invalid signature")

    public_host = os.environ.get("PUBLIC_HOST", "").strip() or request.headers.get("host", "")
    try:
        twiml = build_stream_response(
            public_host,
            call_sid=call_sid,
            from_number=from_number,
            to_number=to_number,
        )
    except Exception:
        logger.exception(
            "phone_webhook_twiml_build_failed call=%s from=%s to=%s public_host=%r",
            call_sid,
            from_number,
            to_number,
            public_host,
        )
        return Response(status_code=500, content="failed to build TwiML response")

    logger.info(
        "phone_webhook_answered call=%s from=%s to=%s public_host=%r",
        call_sid,
        from_number,
        to_number,
        public_host,
    )
    log_event(
        logger,
        "twilio.webhook",
        call=call_sid,
        signature_valid=True,
        ms=(time.monotonic() - webhook_started) * 1000,
    )
    return Response(content=twiml, media_type="text/xml")
