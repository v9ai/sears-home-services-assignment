"""Offline tests for `/debug/latency-probe` (`app/latency_probe.py`, latency O10).

The probe's contract: flag-gated (never mounted unless `LATENCY_PROBE_ENABLED`),
reports every section as a number when the provider answers, reports
`"error: <Type>"` (HTTP 200, never a raise) when it doesn't. All stubs — no network,
no database.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.latency_probe as latency_probe

PROBE_SECTIONS = ("openai_models_ttfb_ms", "llm_ttft_ms", "tts_ttfb_ms", "db_roundtrip_ms")


class _FakeStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        return object()  # first chunk; the probe breaks after one


class _FakeOpenAI:
    """Stub of openai.AsyncOpenAI covering exactly the three calls the probe makes."""

    def __init__(self, *args, **kwargs) -> None:
        class _Models:
            async def list(self):
                return []

        class _Completions:
            async def create(self, **kwargs):
                return _FakeStream()

        class _Chat:
            completions = _Completions()

        class _SpeechResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def iter_bytes(self):
                yield b"\x00"

        class _WithStreaming:
            def create(self, **kwargs):
                return _SpeechResponse()

        class _Speech:
            with_streaming_response = _WithStreaming()

        class _Audio:
            speech = _Speech()

        self.models = _Models()
        self.chat = _Chat()
        self.audio = _Audio()


class _BrokenOpenAI:
    """Every attribute access path ends in a raise — the probe must contain it."""

    def __init__(self, *args, **kwargs) -> None:
        class _Models:
            async def list(self):
                raise ConnectionError("no route to provider")

        class _Completions:
            async def create(self, **kwargs):
                raise TimeoutError("provider timeout")

        class _Chat:
            completions = _Completions()

        class _WithStreaming:
            def create(self, **kwargs):
                raise RuntimeError("tts down")

        class _Speech:
            with_streaming_response = _WithStreaming()

        class _Audio:
            speech = _Speech()

        self.models = _Models()
        self.chat = _Chat()
        self.audio = _Audio()


def _client() -> TestClient:
    test_app = FastAPI()
    test_app.include_router(latency_probe.router)
    return TestClient(test_app)


def _fake_sessionmaker():
    class _Db:
        async def execute(self, stmt):
            return None

    @asynccontextmanager
    async def _session():
        yield _Db()

    return _session


def test_probe_reports_all_sections_with_fakes(monkeypatch):
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    monkeypatch.setattr(latency_probe, "get_sessionmaker", _fake_sessionmaker)

    resp = _client().get("/debug/latency-probe")

    assert resp.status_code == 200
    body = resp.json()
    assert "region_hint" in body
    for section in PROBE_SECTIONS:
        assert isinstance(body[section], int | float), f"{section} not numeric: {body[section]!r}"
        assert body[section] >= 0


def test_probe_never_raises_on_provider_errors(monkeypatch):
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _BrokenOpenAI)

    def _broken_sessionmaker():
        raise RuntimeError("no database configured")

    monkeypatch.setattr(latency_probe, "get_sessionmaker", _broken_sessionmaker)

    resp = _client().get("/debug/latency-probe")

    assert resp.status_code == 200  # the probe reports, never raises
    body = resp.json()
    assert body["openai_models_ttfb_ms"] == "error: ConnectionError"
    assert body["llm_ttft_ms"] == "error: TimeoutError"
    assert body["tts_ttfb_ms"] == "error: RuntimeError"
    assert body["db_roundtrip_ms"] == "error: RuntimeError"


def test_probe_not_mounted_by_default(monkeypatch):
    """`LATENCY_PROBE_ENABLED` off -> the route must not exist on the real app
    (flag-gated debug surface; see app/main.py)."""
    monkeypatch.delenv("LATENCY_PROBE_ENABLED", raising=False)
    from app.main import app as real_app

    paths = {getattr(r, "path", None) for r in real_app.routes}
    assert "/debug/latency-probe" not in paths
