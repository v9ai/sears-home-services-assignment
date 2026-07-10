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


async def test_cloudflare_backend_accepts_explicit_url_without_account_id(monkeypatch):
    """An explicit ``CF_EMAIL_API_URL`` (e.g. a staging gateway) must bypass the
    ``CF_ACCOUNT_ID`` guard — the guard only fires on the default, un-substituted URL."""
    monkeypatch.setenv("EMAIL_BACKEND", "cloudflare")
    monkeypatch.delenv("CF_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("CF_EMAIL_API_URL", "https://staging.example/email/send")

    captured: dict = {}
    _mock_cloudflare_transport(monkeypatch, captured, {"success": True, "result": {}})

    await email_backend.get_email_backend().send(
        to="caller@example.com", subject="subject", body="body"
    )
    assert captured["url"] == "https://staging.example/email/send"


async def test_cloudflare_backend_raises_when_success_false(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "cloudflare")
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct-123")

    _mock_cloudflare_transport(
        monkeypatch,
        {},
        # The documented error response carries ``result: null`` — mock it faithfully so
        # the ``payload.get("result") or {}`` null-guard in the backend stays pinned.
        {"success": False, "errors": [{"message": "sender not verified"}], "result": None},
    )

    with pytest.raises(RuntimeError, match="failed"):
        await email_backend.get_email_backend().send(
            to="caller@example.com", subject="subject", body="body"
        )


async def test_cloudflare_backend_raises_on_http_error_status(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "cloudflare")
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct-123")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"success": False, "errors": []})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        email_backend.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await email_backend.get_email_backend().send(
            to="caller@example.com", subject="subject", body="body"
        )


def test_smtp_backend_reads_env_and_flags_implicit_tls(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@shs.example")

    smtp = email_backend.SmtpEmailBackend()
    assert smtp.host == "smtp.example"
    assert smtp.port == 465  # 465 → implicit TLS branch in send()
    assert smtp.username == "user"
    assert smtp.sender == "no-reply@shs.example"


def _mock_aiosmtplib_send(monkeypatch, captured: dict):
    """Capture the message + kwargs the backend hands to ``aiosmtplib.send``. The
    function-local ``import aiosmtplib`` inside ``send()`` resolves to the same module
    object, so patching the module attribute intercepts the call."""
    import aiosmtplib

    async def fake_send(message, **kwargs):
        captured["message"] = message
        captured["kwargs"] = kwargs

    monkeypatch.setattr(aiosmtplib, "send", fake_send)


async def test_smtp_backend_send_negotiates_starttls_on_port_587(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@shs.example")

    captured: dict = {}
    _mock_aiosmtplib_send(monkeypatch, captured)

    await email_backend.get_email_backend().send(
        to="caller@example.com", subject="subject", body="body"
    )

    message = captured["message"]
    assert message["From"] == "no-reply@shs.example"
    assert message["To"] == "caller@example.com"
    assert message["Subject"] == "subject"
    assert message.get_content().strip() == "body"
    assert captured["kwargs"] == {
        "hostname": "smtp.example",
        "port": 587,
        "username": "user",
        "password": "secret",
        "use_tls": False,
        "start_tls": True,
    }


async def test_smtp_backend_send_uses_implicit_tls_on_port_465(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "smtp")
    monkeypatch.setenv("SMTP_PORT", "465")

    captured: dict = {}
    _mock_aiosmtplib_send(monkeypatch, captured)

    await email_backend.get_email_backend().send(
        to="caller@example.com", subject="subject", body="body"
    )

    assert captured["kwargs"]["port"] == 465
    assert captured["kwargs"]["use_tls"] is True
    assert captured["kwargs"]["start_tls"] is False


def test_smtp_backend_defaults_sender_when_email_from_unset(monkeypatch):
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    assert email_backend.SmtpEmailBackend().sender == "no-reply@example.com"


def test_get_email_backend_choice_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "SMTP")
    assert isinstance(email_backend.get_email_backend(), email_backend.SmtpEmailBackend)


def test_get_email_backend_unknown_value_falls_back_to_console(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "sendgrid")
    assert isinstance(email_backend.get_email_backend(), email_backend.ConsoleEmailBackend)


def test_set_and_reset_email_backend_injection_hook():
    sentinel = email_backend.ConsoleEmailBackend()
    email_backend.set_email_backend(sentinel)
    assert email_backend.get_email_backend() is sentinel
    email_backend.reset_email_backend()
    # After reset the next get() re-reads the env rather than returning the injected one.
    assert email_backend.get_email_backend() is not sentinel


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # An already-@ address with a spoken "dot" in the domain still gets repaired.
        ("caller@example dot com", "caller@example.com"),
        # Multiple spaces around the spoken tokens collapse.
        ("caller    at    example    dot    com", "caller@example.com"),
        ("   ", None),
        ("@example.com", None),
        ("caller@", None),
        ("plainaddress", None),
    ],
)
def test_normalize_email_additional_edges(raw, expected):
    assert normalize_email(raw) == expected


def test_findings_followup_email_handles_no_visible_issues():
    analysis = VisionAnalysis(appliance_detected="dryer", matches_reported_symptoms=False)
    subject, body = findings_followup_email(analysis)
    assert "found" in subject.lower()
    assert "No clear visible issues" in body
    assert "dryer" in body


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
