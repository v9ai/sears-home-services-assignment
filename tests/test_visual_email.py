"""Email module dry-run assertions (validation.md): correct link, correct backend
selection. Never hits a real SMTP/Cloudflare endpoint."""

from __future__ import annotations

import json

import httpx
import pytest

from app.email import backend as email_backend
from app.email.templates import findings_followup_email, upload_link_email
from app.email.validation import normalize_email
from app.vision.schema import VisibleIssue, VisionAnalysis


@pytest.fixture(autouse=True)
def _reset_backend():
    email_backend.reset_email_backend()
    yield
    email_backend.reset_email_backend()


def test_get_email_backend_defaults_to_console(monkeypatch):
    monkeypatch.delenv("EMAIL_BACKEND", raising=False)
    assert isinstance(email_backend.get_email_backend(), email_backend.ConsoleEmailBackend)


def test_get_email_backend_selects_cloudflare(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "cloudflare")
    assert isinstance(email_backend.get_email_backend(), email_backend.CloudflareEmailBackend)


def test_get_email_backend_selects_smtp(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "smtp")
    assert isinstance(email_backend.get_email_backend(), email_backend.SmtpEmailBackend)


async def test_console_backend_records_sends(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    console = email_backend.get_email_backend()
    subject, body = upload_link_email("http://localhost:3000/upload/tok123")
    await console.send(to="caller@example.com", subject=subject, body=body)
    assert console.sent == [{"to": "caller@example.com", "subject": subject, "body": body}]


def test_upload_link_email_contains_the_link():
    subject, body = upload_link_email("http://localhost:3000/upload/tok123")
    assert "upload" in subject.lower()
    assert "http://localhost:3000/upload/tok123" in body


def _mock_cloudflare_transport(monkeypatch, captured: dict, response_json: dict):
    """Route the backend's internally-constructed AsyncClient through a MockTransport."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json=response_json)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        email_backend.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )


async def test_cloudflare_backend_hits_email_sending_endpoint_with_correct_payload(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "cloudflare")
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct-123")
    monkeypatch.setenv("CF_EMAIL_API_TOKEN", "cf-token")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@shs.example")
    monkeypatch.delenv("CF_EMAIL_API_URL", raising=False)

    captured: dict = {}
    _mock_cloudflare_transport(
        monkeypatch,
        captured,
        {
            "success": True,
            "errors": [],
            "result": {"delivered": ["caller@example.com"], "permanent_bounces": [], "queued": []},
        },
    )

    await email_backend.get_email_backend().send(
        to="caller@example.com", subject="subject", body="body"
    )

    assert captured["url"] == (
        "https://api.cloudflare.com/client/v4/accounts/acct-123/email/sending/send"
    )
    assert captured["authorization"] == "Bearer cf-token"
    assert captured["json"] == {
        "to": "caller@example.com",
        "from": {"address": "no-reply@shs.example", "name": "Sears Home Services"},
        "subject": "subject",
        "text": "body",
    }


async def test_cloudflare_backend_raises_on_permanent_bounce(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "cloudflare")
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct-123")
    monkeypatch.setenv("CF_EMAIL_API_TOKEN", "cf-token")

    _mock_cloudflare_transport(
        monkeypatch,
        {},
        {
            "success": True,
            "errors": [],
            "result": {
                "delivered": [],
                "permanent_bounces": ["caller@example.com"],
                "queued": [],
            },
        },
    )

    with pytest.raises(RuntimeError, match="bounced"):
        await email_backend.get_email_backend().send(
            to="caller@example.com", subject="subject", body="body"
        )


async def test_cloudflare_backend_requires_account_id(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "cloudflare")
    monkeypatch.delenv("CF_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CF_EMAIL_API_URL", raising=False)

    with pytest.raises(RuntimeError, match="CF_ACCOUNT_ID"):
        await email_backend.get_email_backend().send(
            to="caller@example.com", subject="subject", body="body"
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("caller@example.com", "caller@example.com"),
        ("  Caller@Example.COM  ", "caller@example.com"),
        ("mailto:caller@example.com", "caller@example.com"),
        ("caller@example.com.", "caller@example.com"),
        ("d dot martinez99 at gmail dot com", "d.martinez99@gmail.com"),
        ("D dot Martinez99 at Gmail dot com.", "d.martinez99@gmail.com"),
        ("caller at example dot com", "caller@example.com"),
        ("d.martinez99@gmail.com", "d.martinez99@gmail.com"),
        ("", None),
        (None, None),
        ("not an email", None),
        ("caller@example", None),
        ("two@at@signs.com", None),
    ],
)
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


def test_findings_followup_email_cites_visible_issues():
    analysis = VisionAnalysis(
        appliance_detected="washer",
        brand_guess="Kenmore",
        visible_issues=[
            VisibleIssue(issue="drum seal cracked", confidence=0.8, evidence="visible tear")
        ],
        matches_reported_symptoms=True,
        additional_steps=["Check the door gasket for tears."],
    )
    subject, body = findings_followup_email(analysis)
    assert "found" in subject.lower()
    assert "drum seal cracked" in body
    assert "Kenmore" in body
    assert "Check the door gasket for tears." in body
