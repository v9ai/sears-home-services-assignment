"""Email backend, switched by ``EMAIL_BACKEND`` (tech-stack.md → Secrets).

``console`` (default, offline demo) logs the email and records it for tests;
``smtp`` sends via ``aiosmtplib``; ``cloudflare`` is the real Tier-3 backend
(requirements.md §Decisions #3) — one vendor with the Cloudflare-hosted containers,
sender domain/address verified in the Cloudflare dashboard.
"""

from __future__ import annotations

import logging
import os
from email.message import EmailMessage
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class EmailBackend(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailBackend:
    """Offline-demo backend: logs instead of sending, and records every send for
    tests/dry-run assertions."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})
        logger.info("EMAIL[console] to=%s subject=%s\n%s", to, subject, body)


class SmtpEmailBackend:
    """``aiosmtplib`` fallback. Reads ``SMTP_HOST``/``SMTP_PORT``/``SMTP_USERNAME``/
    ``SMTP_PASSWORD`` (not yet in ``.env.example`` — see plan.md Integration deltas)
    plus the shared ``EMAIL_FROM``."""

    def __init__(self) -> None:
        self.host = os.environ.get("SMTP_HOST", "localhost")
        self.port = int(os.environ.get("SMTP_PORT", "587"))
        self.username = os.environ.get("SMTP_USERNAME")
        self.password = os.environ.get("SMTP_PASSWORD")
        self.sender = os.environ.get("EMAIL_FROM", "no-reply@example.com")

    async def send(self, to: str, subject: str, body: str) -> None:
        import aiosmtplib

        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        await aiosmtplib.send(
            message,
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            start_tls=True,
        )


class CloudflareEmailBackend:
    """Cloudflare Email Service HTTP API (requirements.md §Decisions #3)."""

    def __init__(self) -> None:
        self.api_token = os.environ.get("CF_EMAIL_API_TOKEN", "")
        self.sender = os.environ.get("EMAIL_FROM", "no-reply@example.com")
        self.api_url = os.environ.get(
            "CF_EMAIL_API_URL", "https://api.cloudflare.com/client/v4/accounts/email/messages"
        )

    async def send(self, to: str, subject: str, body: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": self.sender},
                    "subject": subject,
                    "content": [{"type": "text/plain", "value": body}],
                },
            )
            response.raise_for_status()


_backend: EmailBackend | None = None


def get_email_backend() -> EmailBackend:
    """Lazily construct (and cache) the backend selected by ``EMAIL_BACKEND``."""
    global _backend
    if _backend is not None:
        return _backend

    choice = os.environ.get("EMAIL_BACKEND", "console").lower()
    if choice == "cloudflare":
        _backend = CloudflareEmailBackend()
    elif choice == "smtp":
        _backend = SmtpEmailBackend()
    else:
        _backend = ConsoleEmailBackend()
    return _backend


def set_email_backend(backend: EmailBackend) -> None:
    """Test hook — inject a fake/console backend without touching ``EMAIL_BACKEND``."""
    global _backend
    _backend = backend


def reset_email_backend() -> None:
    """Test hook — force the next ``get_email_backend()`` to re-read the env."""
    global _backend
    _backend = None
