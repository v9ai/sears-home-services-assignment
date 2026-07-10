"""Vision-client error/parse coverage — the real model call is mocked, no API key.

``app.vision.client.analyze_image`` was exercised only via injected canned analyses
elsewhere, so its own request construction, response parsing, and failure surface were
untested. Here we drive a fake ``AsyncOpenAI``-shaped client (success, provider errors,
timeout, and malformed/schema-invalid responses) plus the two pure helpers
(``_case_file_summary`` / ``_image_data_uri``). Fully hermetic: filesystem tmp images,
no network, no ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import base64
import json
import uuid

import httpx
import openai
import pytest

from app.contracts import CaseFile, Symptom
from app.uploads.store import InMemoryUploadStore, set_store
from app.vision import client as vision_client
from app.vision.client import _case_file_summary, _image_data_uri, analyze_image
from app.vision.schema import VisionAnalysis

_VALID_PAYLOAD = {
    "appliance_detected": "washer",
    "brand_guess": "Kenmore",
    "visible_issues": [
        {"issue": "cracked drum seal", "confidence": 0.82, "evidence": "visible tear"}
    ],
    "matches_reported_symptoms": True,
    "additional_steps": ["Inspect the door gasket."],
}


# --------------------------------------------------------------------- fake OpenAI client


class _FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str | None) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, *, content: str | None = None, error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.calls: list[dict] = []

    async def create(self, **kwargs) -> _FakeResponse:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._content)


class FakeOpenAI:
    """Mimics just the ``client.chat.completions.create`` surface ``analyze_image`` uses."""

    def __init__(self, *, content: str | None = None, error: Exception | None = None) -> None:
        self.completions = _FakeCompletions(content=content, error=error)
        self.chat = type("_Chat", (), {"completions": self.completions})()


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "appliance.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-body")
    return path


# --------------------------------------------------------------------- success path


async def test_success_parses_into_the_vision_analysis_contract(image):
    fake = FakeOpenAI(content=json.dumps(_VALID_PAYLOAD))
    result = await analyze_image(str(image), CaseFile(), client=fake)

    assert isinstance(result, VisionAnalysis)
    assert result.appliance_detected == "washer"
    assert result.brand_guess == "Kenmore"
    assert result.visible_issues[0].issue == "cracked drum seal"
    assert result.additional_steps == ["Inspect the door gasket."]


async def test_success_sends_expected_request_shape(image):
    fake = FakeOpenAI(content=json.dumps(_VALID_PAYLOAD))
    cf = CaseFile(appliance_type="dryer", brand="Whirlpool")
    await analyze_image(str(image), cf, client=fake)

    assert len(fake.completions.calls) == 1
    kwargs = fake.completions.calls[0]
    assert kwargs["model"] == vision_client.VISION_MODEL
    assert kwargs["response_format"]["json_schema"]["name"] == "vision_analysis"

    messages = kwargs["messages"]
    assert messages[0]["role"] == "system"
    user_content = messages[1]["content"]
    text_part = next(p for p in user_content if p["type"] == "text")
    image_part = next(p for p in user_content if p["type"] == "image_url")
    assert "dryer" in text_part["text"]  # case-file context is passed to the model
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_empty_json_object_parses_to_all_defaults(image):
    """The schema's fields are all optional/defaulted, so a minimal ``{}`` still yields a
    valid (empty) analysis rather than blowing up."""
    fake = FakeOpenAI(content="{}")
    result = await analyze_image(str(image), CaseFile(), client=fake)
    assert result.appliance_detected is None
    assert result.visible_issues == []
    assert result.matches_reported_symptoms is False


# --------------------------------------------------------------------- provider failures
# analyze_image has no try/except: whatever the model client raises propagates to the
# caller. These pin that actual contract (and that there is NO retry).


@pytest.mark.parametrize(
    "error",
    [
        openai.APIConnectionError(message="connection reset", request=_request()),
        openai.APITimeoutError(request=_request()),
        openai.RateLimitError(
            message="rate limited", response=httpx.Response(429, request=_request()), body=None
        ),
        openai.InternalServerError(
            message="server error", response=httpx.Response(500, request=_request()), body=None
        ),
    ],
    ids=["connection", "timeout", "rate_limit", "server_error"],
)
async def test_provider_errors_propagate(image, error):
    fake = FakeOpenAI(error=error)
    with pytest.raises(type(error)):
        await analyze_image(str(image), CaseFile(), client=fake)


async def test_provider_error_is_not_retried(image):
    """No application-level retry: a failing call is attempted exactly once."""
    fake = FakeOpenAI(
        error=openai.RateLimitError(
            message="rl", response=httpx.Response(429, request=_request()), body=None
        )
    )
    with pytest.raises(openai.RateLimitError):
        await analyze_image(str(image), CaseFile(), client=fake)
    assert len(fake.completions.calls) == 1


# --------------------------------------------------------------------- malformed responses


async def test_unparseable_json_raises_json_error(image):
    fake = FakeOpenAI(content="not json {{{")
    with pytest.raises(json.JSONDecodeError):
        await analyze_image(str(image), CaseFile(), client=fake)


async def test_none_content_raises_type_error(image):
    """A model turn with no content (``choices[0].message.content is None``) can't be
    json-decoded — pins that this surfaces as a TypeError, not a silent empty analysis."""
    fake = FakeOpenAI(content=None)
    with pytest.raises(TypeError):
        await analyze_image(str(image), CaseFile(), client=fake)


async def test_schema_invalid_payload_raises_validation_error(image):
    from pydantic import ValidationError

    bad = json.dumps(
        {
            "appliance_detected": "washer",
            "visible_issues": [
                {"issue": "x", "confidence": 5.0, "evidence": "y"}  # confidence > 1.0
            ],
        }
    )
    fake = FakeOpenAI(content=bad)
    with pytest.raises(ValidationError):
        await analyze_image(str(image), CaseFile(), client=fake)


# --------------------------------------------------------------------- pure helpers


def test_case_file_summary_without_symptoms():
    summary = _case_file_summary(CaseFile())
    assert "Appliance: unknown" in summary
    assert "Reported symptoms: none captured yet" in summary


def test_case_file_summary_includes_brand_and_symptom_detail():
    cf = CaseFile(
        appliance_type="dishwasher",
        brand="Bosch",
        symptoms=[
            Symptom(description="won't drain", onset="2 days ago", error_code="E24", sound="hum")
        ],
    )
    summary = _case_file_summary(cf)
    assert "Appliance: dishwasher" in summary
    assert "Brand: Bosch" in summary
    assert "won't drain" in summary
    assert "error code E24" in summary
    assert "sound: hum" in summary


@pytest.mark.parametrize(
    ("filename", "expected_mime"),
    [
        ("photo.jpg", "image/jpeg"),
        ("photo.png", "image/png"),
        ("photo.webp", "image/webp"),
        ("photo.noext", "image/jpeg"),  # unknown extension → default mime
    ],
)
def test_image_data_uri_mime_and_roundtrip(tmp_path, filename, expected_mime):
    body = b"\x00\x01\x02payload-bytes"
    path = tmp_path / filename
    path.write_bytes(body)

    uri = _image_data_uri(str(path))
    assert uri.startswith(f"data:{expected_mime};base64,")
    encoded = uri.split(",", 1)[1]
    assert base64.b64decode(encoded) == body


# ------------------------------------------------- resilience + bounded retry (tasks #25/#34)
# The background analysis task must never leave an upload stuck at 'uploaded' when the
# vision call fails. Transient errors (connection/timeout/rate-limit) are retried a bounded
# number of times; everything else fails immediately. On give-up it marks the upload
# terminally 'failed', and the agent tool surfaces that honestly.


@pytest.fixture
def _session_ctx():
    """Seed the per-turn ContextVars check_image_analysis reads."""
    sid = uuid.uuid4()
    cf = CaseFile()
    from app.agent.state import current_case_file, current_session_id

    cf_token = current_case_file.set(cf)
    sid_token = current_session_id.set(sid)
    yield sid, cf
    current_case_file.reset(cf_token)
    current_session_id.reset(sid_token)


@pytest.fixture
def no_sleep(monkeypatch):
    """Neutralize backoff sleeps (keep tests instant) while recording how many happened."""
    from app.uploads import routes as upload_routes

    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(upload_routes.asyncio, "sleep", _fake_sleep)
    return slept


async def _seed_uploaded(store) -> str:
    record = await store.create(uuid.uuid4(), "caller@example.com")
    await store.save_image(record.token, "data/uploads/fake.jpg")  # status → 'uploaded'
    return record.token


async def test_background_analysis_retries_transient_then_succeeds(monkeypatch, no_sleep):
    """A transient timeout on the first attempt clears on retry → ends 'analyzed', never
    'failed', and does not strand the upload."""
    from app.uploads import routes as upload_routes

    store = InMemoryUploadStore()
    set_store(store)
    token = await _seed_uploaded(store)

    attempts = {"n": 0}

    async def _flaky(rec):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise openai.APITimeoutError(request=_request())
        await store.save_analysis(rec.token, {"appliance_detected": "washer"})

    monkeypatch.setattr(upload_routes, "run_vision_pipeline", _flaky)

    await upload_routes._analyze_in_background(token)

    final = await store.get_by_token(token)
    assert final is not None
    assert final.status == "analyzed"
    assert attempts["n"] == 2  # one retry was enough
    assert len(no_sleep) == 1  # exactly one backoff before the successful retry


async def test_background_analysis_marks_failed_after_exhausting_retries(monkeypatch, no_sleep):
    """A persistent transient error is retried up to the bound, then the upload is marked
    terminally 'failed' (3 attempts total = 1 try + 2 retries, 2 backoffs)."""
    from app.uploads import routes as upload_routes

    store = InMemoryUploadStore()
    set_store(store)
    token = await _seed_uploaded(store)

    attempts = {"n": 0}

    async def _always_down(_rec):
        attempts["n"] += 1
        raise openai.APIConnectionError(message="vision down", request=_request())

    monkeypatch.setattr(upload_routes, "run_vision_pipeline", _always_down)

    await upload_routes._analyze_in_background(token)  # must not raise

    final = await store.get_by_token(token)
    assert final is not None
    assert final.status == "failed"
    assert attempts["n"] == len(upload_routes._VISION_RETRY_BACKOFFS_S) + 1 == 3
    assert len(no_sleep) == len(upload_routes._VISION_RETRY_BACKOFFS_S)  # one backoff per retry


async def test_background_analysis_non_transient_fails_immediately_without_retry(
    monkeypatch, no_sleep
):
    """A schema/validation-shaped error is deterministic — fail on the first attempt with
    no retry and no backoff."""
    from pydantic import ValidationError

    from app.uploads import routes as upload_routes

    store = InMemoryUploadStore()
    set_store(store)
    token = await _seed_uploaded(store)

    # A real ValidationError (confidence out of range) — representative non-transient failure.
    try:
        VisionAnalysis(visible_issues=[{"issue": "x", "confidence": 5.0, "evidence": "y"}])
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        validation_error = exc

    attempts = {"n": 0}

    async def _bad(_rec):
        attempts["n"] += 1
        raise validation_error

    monkeypatch.setattr(upload_routes, "run_vision_pipeline", _bad)

    await upload_routes._analyze_in_background(token)

    final = await store.get_by_token(token)
    assert final is not None
    assert final.status == "failed"
    assert attempts["n"] == 1  # no retry
    assert no_sleep == []  # no backoff


async def test_background_analysis_success_still_marks_analyzed(monkeypatch):
    from app.uploads import routes as upload_routes

    store = InMemoryUploadStore()
    set_store(store)
    token = await _seed_uploaded(store)

    async def _ok(rec):
        await store.save_analysis(rec.token, {"appliance_detected": "washer"})

    monkeypatch.setattr(upload_routes, "run_vision_pipeline", _ok)

    await upload_routes._analyze_in_background(token)

    final = await store.get_by_token(token)
    assert final is not None
    assert final.status == "analyzed"  # first-try success unchanged, no retry path taken


async def test_check_image_analysis_surfaces_failed_state(_session_ctx):
    from app.tools import visual_tools

    sid, _cf = _session_ctx
    store = InMemoryUploadStore()
    set_store(store)
    record = await store.create(sid, "caller@example.com")
    await store.save_image(record.token, "data/uploads/fake.jpg")
    await store.mark_failed(record.token)

    result = await visual_tools.check_image_analysis()
    assert "still being analyzed" not in result
    assert "didn't complete" in result
