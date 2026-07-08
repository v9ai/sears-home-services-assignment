"""Email module dry-run assertions (validation.md): correct link, correct backend
selection. Never hits a real SMTP/Cloudflare endpoint."""

from __future__ import annotations

import pytest

from app.email import backend as email_backend
from app.email.templates import findings_followup_email, upload_link_email
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
