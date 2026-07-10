"""Offline tests for the web-channel TTS provider adapter (loop v2 f3) —
`app/agent/tts.py`: provider dispatch, Cartesia SSE parsing, format mapping, and
missing-key failure. No network; the Cartesia branch is exercised via monkeypatch.
"""

from __future__ import annotations

import base64
import json

import pytest

from app.agent import tts


def test_default_provider_is_openai(monkeypatch):
    """No env -> the OpenAI branch (the h2 flip has NOT landed; default unchanged)."""
    monkeypatch.delenv("WEB_TTS_PROVIDER", raising=False)
    called = {"cartesia": False}

    async def fake_cartesia(text, *, response_format):
        called["cartesia"] = True
        yield b"x"

    monkeypatch.setattr(tts, "_synthesize_cartesia", fake_cartesia)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tts._client.cache_clear()

    async def run():
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            async for _ in tts.synthesize("hello"):
                pass

    import asyncio

    asyncio.run(run())
    assert called["cartesia"] is False  # never routed to cartesia
    tts._client.cache_clear()


async def test_cartesia_provider_routes_to_adapter(monkeypatch):
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")
    chunks_out = [b"aa", b"bb"]

    async def fake_cartesia(text, *, response_format):
        assert text == "hello there"
        assert response_format == "pcm"
        for c in chunks_out:
            yield c

    monkeypatch.setattr(tts, "_synthesize_cartesia", fake_cartesia)

    got = [c async for c in tts.synthesize("hello there", response_format="pcm")]

    assert got == chunks_out


async def test_cartesia_missing_keys_raise(monkeypatch):
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    monkeypatch.delenv("CARTESIA_VOICE_ID", raising=False)

    with pytest.raises(RuntimeError, match="CARTESIA_API_KEY"):
        async for _ in tts.synthesize("hello", response_format="pcm"):
            pass


async def test_cartesia_mp3_falls_back_to_openai(monkeypatch):
    """Cartesia's SSE endpoint rejects mp3 (measured 400) — legacy mp3 requests must
    route to OpenAI even with the provider env set, so the h2 default flip can't
    break old-format web clients."""
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "v")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tts._client.cache_clear()

    routed_cartesia = {"hit": False}

    async def fake_cartesia(text, *, response_format):
        routed_cartesia["hit"] = True
        yield b"x"

    monkeypatch.setattr(tts, "_synthesize_cartesia", fake_cartesia)

    # mp3 must go down the OpenAI branch: with no OPENAI key that branch raises,
    # proving the route (and cartesia was never called).
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        async for _ in tts.synthesize("hello", response_format="mp3"):
            pass
    assert routed_cartesia["hit"] is False
    tts._client.cache_clear()


def test_parse_sse_audio_chunk_decodes_b64():
    audio = b"\x01\x02\x03\x04"
    line = "data: " + json.dumps({"type": "chunk", "data": base64.b64encode(audio).decode()})

    assert tts._parse_sse_audio_chunk(line) == audio


@pytest.mark.parametrize(
    "line",
    [
        "data: " + json.dumps({"type": "done"}),  # terminal event
        "data: not-json",  # malformed
        ": keepalive",  # SSE comment
        "",  # blank line between events
        "event: message",  # non-data field
    ],
)
def test_parse_sse_audio_chunk_ignores_non_audio(line):
    assert tts._parse_sse_audio_chunk(line) is None


def test_cartesia_output_format_mapping():
    # pcm matches the web channel's 24kHz frames (O9/O12); mp3 is deliberately absent
    # (Cartesia SSE 400s on it — legacy mp3 stays on OpenAI).
    assert tts._CARTESIA_OUTPUT_FORMATS == {
        "pcm": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000},
    }


def test_empty_text_yields_nothing(monkeypatch):
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")

    import asyncio

    async def run():
        return [c async for c in tts.synthesize("   ")]

    assert asyncio.run(run()) == []
