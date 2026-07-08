"""``X-Twilio-Signature`` validation for the voice webhook.

Per requirements.md Decision 6: ``TWILIO_AUTH_TOKEN`` must be the Account Auth Token
(Console -> Account Info), never an API Key secret -- Twilio's signature algorithm is
keyed to the Auth Token specifically. Secrets come from the environment only (mission
non-negotiable 5); this module never hardcodes or logs the token.
"""

from __future__ import annotations

import os

from twilio.request_validator import RequestValidator


class SignatureConfigError(Exception):
    """Raised when ``TWILIO_AUTH_TOKEN`` is missing -- a misconfiguration, not a caller
    error, so webhook code should turn this into a loud 5xx rather than a quiet 403."""


def get_validator(auth_token: str | None = None) -> RequestValidator:
    token = auth_token if auth_token is not None else os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not token:
        raise SignatureConfigError("TWILIO_AUTH_TOKEN is not configured")
    return RequestValidator(token)


def validate_request(
    url: str,
    params: dict[str, str],
    signature: str | None,
    *,
    auth_token: str | None = None,
) -> bool:
    """True only for a present, correctly-signed request. Never raises for a bad/absent
    signature -- callers should treat any falsy result as a 403."""
    if not signature:
        return False
    validator = get_validator(auth_token)
    return validator.validate(url, params, signature)
