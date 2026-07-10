"""Prewarm must gate on the key of the provider it will actually use (B3).

Before the fix, ``prewarm`` returned early unless ``OPENAI_API_KEY`` was set —
but the default web TTS provider for ``pcm`` is Cartesia. A Cartesia-only
deployment (the shipped default) silently never warmed the cache, and an
OpenAI-key-only deployment attempted a Cartesia synth that could only fail.
These tests pin the provider-aware gate for every configuration.
"""

from __future__ import annotations

import pytest

from app.agent import tts, tts_cache

_ALL_KEYS = ("OPENAI_API_KEY", "CARTESIA_API_KEY", "CARTESIA_VOICE_ID", "WEB_TTS_PROVIDER")


@pytest.fixture
def warm_env(monkeypatch, tmp_path):
    """Clean provider env, empty cache dir, and a recording fake synth."""
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    calls: list[tuple[str, str]] = []

    async def fake_synthesize(text, *, voice="alloy", response_format="mp3"):
        calls.append((text, response_format))
        yield b"audio"

    monkeypatch.setattr(tts, "synthesize", fake_synthesize)
    return calls


async def test_cartesia_only_deployment_prewarms_pcm(monkeypatch, warm_env) -> None:
    # The shipped default: Cartesia provider, Cartesia creds, no OpenAI key.
    monkeypatch.setenv("CARTESIA_API_KEY", "ck")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "cv")
    await tts_cache.prewarm(formats=("pcm",))
    assert warm_env, "prewarm skipped a fully-configured Cartesia deployment"
    assert {fmt for _, fmt in warm_env} == {"pcm"}


async def test_openai_key_alone_does_not_attempt_cartesia_pcm(monkeypatch, warm_env) -> None:
    # OpenAI key only, provider left at default cartesia: pcm would dispatch to
    # Cartesia, whose creds are absent — prewarm must skip cleanly, not attempt.
    monkeypatch.setenv("OPENAI_API_KEY", "ok")
    await tts_cache.prewarm(formats=("pcm",))
    assert warm_env == []


async def test_openai_provider_override_prewarms_pcm(monkeypatch, warm_env) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "ok")
    monkeypatch.setenv("WEB_TTS_PROVIDER", "openai")
    await tts_cache.prewarm(formats=("pcm",))
    assert warm_env and {fmt for _, fmt in warm_env} == {"pcm"}


async def test_mp3_always_gates_on_openai_key(monkeypatch, warm_env) -> None:
    # mp3 falls through to OpenAI regardless of provider; Cartesia creds alone
    # must not warm it, an OpenAI key must.
    monkeypatch.setenv("CARTESIA_API_KEY", "ck")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "cv")
    await tts_cache.prewarm(formats=("mp3",))
    assert warm_env == []
    monkeypatch.setenv("OPENAI_API_KEY", "ok")
    await tts_cache.prewarm(formats=("mp3",))
    assert warm_env and {fmt for _, fmt in warm_env} == {"mp3"}


async def test_no_keys_at_all_is_a_noop(warm_env) -> None:
    await tts_cache.prewarm(formats=("pcm", "mp3"))
    assert warm_env == []


async def test_mixed_formats_warm_only_the_ready_provider(monkeypatch, warm_env) -> None:
    # Cartesia creds only: pcm warms, mp3 (OpenAI) is skipped — per-format gating.
    monkeypatch.setenv("CARTESIA_API_KEY", "ck")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "cv")
    await tts_cache.prewarm(formats=("pcm", "mp3"))
    assert warm_env, "pcm lane should have warmed"
    assert {fmt for _, fmt in warm_env} == {"pcm"}
