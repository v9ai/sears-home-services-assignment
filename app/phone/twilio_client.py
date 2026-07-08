"""Twilio REST API client wrapper.

Used to look up native Twilio call recordings for a given ``CallSid`` (see
``app/phone/twiml.py`` for where recording is turned on, and
``app/recordings/routes.py`` for where this is consumed). Credentials come from the
environment only (mission non-negotiable 5), mirroring ``app/phone/signature.py``'s
loud-misconfiguration convention.
"""

from __future__ import annotations

import os

from twilio.rest import Client


class TwilioConfigError(Exception):
    """Raised when ``TWILIO_ACCOUNT_SID``/``TWILIO_AUTH_TOKEN`` are missing -- a
    misconfiguration, not a caller error, so route code should turn this into a loud
    5xx rather than silently returning no recordings."""


def get_twilio_client(*, account_sid: str | None = None, auth_token: str | None = None) -> Client:
    sid = account_sid if account_sid is not None else os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = auth_token if auth_token is not None else os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        raise TwilioConfigError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must both be configured")
    return Client(sid, token)
