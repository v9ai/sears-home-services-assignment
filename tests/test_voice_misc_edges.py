"""Misc thin edges from the coverage audit (bugfix-loop T15).

Five small unexercised branches, one suite: `for_call(None)`'s uuid4 fallback,
`bind()`'s ContextVar restore semantics, the three non-TTFB `_log_metric`
branches, `SpeechPipeline`'s emit-failure containment, the webhook's
TwiML-build-failure 500, and the `/ws/twilio` `customParameters.CallSid`
fallback.
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.agent.state import current_case_file, current_session_id
from app.agent.tts_pipeline import SpeechPipeline
from app.contracts import CaseFile

pytest.importorskip("pipecat.frames.frames")
from pipecat.metrics.metrics import (  # noqa: E402
    LLMTokenUsage,
    LLMUsageMetricsData,
    TTFBMetricsData,
    TTSUsageMetricsData,
)

import app.voice.routes as routes_module  # noqa: E402
from app.voice.metrics import VoiceMetricsObserver  # noqa: E402
from app.voice.session import VoiceSession  # noqa: E402

VOICE_LOGGER = "app.voice.metrics"


# --- VoiceSession.for_call(None) + bind() restore --------------------------------


def test_for_call_none_mints_distinct_random_v4_ids() -> None:
    a = VoiceSession.for_call(None)
    b = VoiceSession.for_call(None)
    assert a.call_sid is None and b.call_sid is None
    assert a.session_id != b.session_id
    assert a.session_id.version == 4
    # Deterministic v5 path unchanged for real CallSids.
    assert VoiceSession.for_call("CA1").session_id == VoiceSession.for_call("CA1").session_id


def test_bind_restores_prior_context_and_nests() -> None:
    outer_cf, outer_sid = CaseFile(brand="Outer"), uuid.uuid4()
    cf_token = current_case_file.set(outer_cf)
    sid_token = current_session_id.set(outer_sid)
    try:
        session = VoiceSession.for_call("CA-bind")
        with session.bind():
            assert current_case_file.get() is session.case_file
            assert current_session_id.get() == session.session_id
            inner = VoiceSession.for_call("CA-inner")
            with inner.bind():
                assert current_session_id.get() == inner.session_id
            # Nested exit restores the enclosing bind, not the outer ambient.
            assert current_session_id.get() == session.session_id
        assert current_case_file.get() is outer_cf
        assert current_session_id.get() == outer_sid
    finally:
        current_case_file.reset(cf_token)
        current_session_id.reset(sid_token)


# --- _log_metric non-TTFB branches -------------------------------------------------


class _Recorder:
    def record(self, *a, **k) -> None: ...


@pytest.fixture
def observer() -> VoiceMetricsObserver:
    return VoiceMetricsObserver(recorder=_Recorder())


def test_llm_usage_metric_logs_token_counts(observer, caplog) -> None:
    metric = LLMUsageMetricsData(
        processor="llm",
        value=LLMTokenUsage(prompt_tokens=21, completion_tokens=8, total_tokens=29),
    )
    with caplog.at_level(logging.INFO, logger=VOICE_LOGGER):
        observer._log_metric(metric)
    assert "event=voice.metrics.llm_usage" in caplog.text
    assert "prompt_tokens=21" in caplog.text and "completion_tokens=8" in caplog.text


def test_tts_usage_metric_logs_characters(observer, caplog) -> None:
    metric = TTSUsageMetricsData(processor="tts", value=137)
    with caplog.at_level(logging.INFO, logger=VOICE_LOGGER):
        observer._log_metric(metric)
    assert "event=voice.metrics.tts_usage" in caplog.text
    assert "characters=137" in caplog.text


def test_ttfb_metric_converts_seconds_to_ms(observer, caplog) -> None:
    with caplog.at_level(logging.INFO, logger=VOICE_LOGGER):
        observer._log_metric(TTFBMetricsData(processor="stt", value=0.25))
    assert "event=voice.metrics.ttfb" in caplog.text
    assert "value_ms=250" in caplog.text


# --- SpeechPipeline emit-failure containment ---------------------------------------


async def test_emit_failure_marks_turn_failed_but_keeps_draining() -> None:
    emitted: list[int] = []

    async def synth(text: str):
        yield b"chunk"

    async def emit(idx: int, text: str, chunk: bytes) -> None:
        if idx == 0:
            raise ConnectionError("consumer died")
        emitted.append(idx)

    pipeline = SpeechPipeline(synth, emit, lookahead=2)
    pipeline.feed("first sentence.")
    pipeline.feed("second sentence.")
    ok = await pipeline.drain()
    assert ok is False, "a dead consumer must fail the turn"
    assert emitted == [1], "later sentences still drain after an emit failure"


# --- webhook TwiML-build-failure → 500 ---------------------------------------------

TEST_AUTH_TOKEN = "test-auth-token-not-a-secret"  # noqa: S105 — fixture value
FORM = {"CallSid": "CA123", "From": "+15551234567", "To": "+13186468479"}
URL = "https://example.ngrok.app/twilio/voice"


def test_twiml_build_failure_returns_500_without_leaking(monkeypatch) -> None:
    from app.phone.webhook import router

    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TEST_AUTH_TOKEN)
    monkeypatch.setenv("PUBLIC_HOST", "example.ngrok.app")

    def boom(*args, **kwargs):
        raise ValueError("secret internals: wss://oops")

    monkeypatch.setattr("app.phone.webhook.build_stream_response", boom)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    signature = RequestValidator(TEST_AUTH_TOKEN).compute_signature(URL, FORM)
    resp = client.post("/twilio/voice", data=FORM, headers={"X-Twilio-Signature": signature})
    assert resp.status_code == 500
    assert resp.text == "failed to build TwiML response"
    assert "secret internals" not in resp.text


# --- /ws/twilio customParameters.CallSid fallback -----------------------------------


class FakeWebSocket:
    def __init__(self, messages: list) -> None:
        self._messages = list(messages)
        self.accepted = False
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        from starlette.websockets import WebSocketDisconnect

        if not self._messages:
            raise WebSocketDisconnect()
        return self._messages.pop(0)

    async def close(self) -> None:
        self.closed = True


async def test_call_sid_resolves_from_custom_parameters(monkeypatch) -> None:
    calls: list[tuple] = []

    async def fake_run_bot(websocket, stream_sid, call_sid):
        calls.append((stream_sid, call_sid))

    monkeypatch.setattr(routes_module, "run_bot", fake_run_bot)
    start = json.dumps(
        {
            "event": "start",
            "start": {"streamSid": "MZ9", "customParameters": {"CallSid": "CA-custom"}},
        }
    )
    await routes_module.twilio_media_stream(FakeWebSocket([start]))
    assert calls == [("MZ9", "CA-custom")]
