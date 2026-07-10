"""Offline tests for the web-channel TTS provider adapter (loop v2 f3) —
`app/agent/tts.py`: provider dispatch, Cartesia SSE parsing, format mapping, and
missing-key failure. No network; the Cartesia branch is exercised via monkeypatch.
"""

from __future__ import annotations

import base64
import json

import pytest

from app.agent import tts


async def test_default_provider_is_cartesia_for_pcm(monkeypatch):
    """h2 flip (user decision 2026-07-10): no env -> pcm requests route to Cartesia."""
    monkeypatch.delenv("WEB_TTS_PROVIDER", raising=False)
    routed = {"cartesia": False}

    async def fake_cartesia(text, *, response_format):
        routed["cartesia"] = True
        assert response_format == "pcm"
        yield b"x"

    monkeypatch.setattr(tts, "_synthesize_cartesia", fake_cartesia)

    got = [c async for c in tts.synthesize("hello", response_format="pcm")]

    assert routed["cartesia"] is True
    assert got == [b"x"]


def test_default_provider_mp3_still_openai(monkeypatch):
    """Even post-flip, mp3 (legacy blob path) stays on OpenAI."""
    monkeypatch.delenv("WEB_TTS_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tts._client.cache_clear()
    routed = {"cartesia": False}

    async def fake_cartesia(text, *, response_format):
        routed["cartesia"] = True
        yield b"x"

    monkeypatch.setattr(tts, "_synthesize_cartesia", fake_cartesia)

    import asyncio

    async def run():
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            async for _ in tts.synthesize("hello", response_format="mp3"):
                pass

    asyncio.run(run())
    assert routed["cartesia"] is False
    tts._client.cache_clear()


async def test_openai_optout_respected(monkeypatch):
    """WEB_TTS_PROVIDER=openai swaps back even for pcm (the recorded escape hatch)."""
    monkeypatch.setenv("WEB_TTS_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tts._client.cache_clear()
    routed = {"cartesia": False}

    async def fake_cartesia(text, *, response_format):
        routed["cartesia"] = True
        yield b"x"

    monkeypatch.setattr(tts, "_synthesize_cartesia", fake_cartesia)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        async for _ in tts.synthesize("hello", response_format="pcm"):
            pass
    assert routed["cartesia"] is False
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


async def test_empty_text_never_touches_a_provider(monkeypatch):
    """The empty-text short-circuit happens before provider dispatch — neither branch runs."""
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")
    hit = {"cartesia": False}

    async def fake_cartesia(text, *, response_format):
        hit["cartesia"] = True
        yield b"x"

    monkeypatch.setattr(tts, "_synthesize_cartesia", fake_cartesia)

    assert [c async for c in tts.synthesize("", response_format="pcm")] == []
    assert hit["cartesia"] is False


@pytest.mark.parametrize("raw", ["cartesia", "CARTESIA", "  Cartesia ", "cArTeSiA"])
async def test_provider_env_is_case_and_whitespace_normalized(monkeypatch, raw):
    """`WEB_TTS_PROVIDER` is `.strip().lower()`-normalized, so operator typos in casing or
    stray spaces still route to Cartesia rather than silently falling back to OpenAI."""
    monkeypatch.setenv("WEB_TTS_PROVIDER", raw)
    routed = {"cartesia": False}

    async def fake_cartesia(text, *, response_format):
        routed["cartesia"] = True
        yield b"c"

    monkeypatch.setattr(tts, "_synthesize_cartesia", fake_cartesia)

    got = [c async for c in tts.synthesize("hello", response_format="pcm")]

    assert routed["cartesia"] is True
    assert got == [b"c"]


async def test_unknown_provider_value_falls_back_to_openai(monkeypatch):
    """An unrecognized provider name isn't Cartesia, so pcm requests take the OpenAI branch
    (which raises without a key) — an unknown value degrades to the default vendor, never to
    a silent no-audio."""
    monkeypatch.setenv("WEB_TTS_PROVIDER", "bogus-vendor")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tts._client.cache_clear()
    routed = {"cartesia": False}

    async def fake_cartesia(text, *, response_format):
        routed["cartesia"] = True
        yield b"c"

    monkeypatch.setattr(tts, "_synthesize_cartesia", fake_cartesia)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        async for _ in tts.synthesize("hello", response_format="pcm"):
            pass
    assert routed["cartesia"] is False
    tts._client.cache_clear()


def test_parse_sse_audio_chunk_ignores_chunk_with_empty_data():
    """A well-formed `chunk` event carrying an empty `data` field yields no audio (the
    `payload.get("data")` truthiness guard) rather than an empty-string b64 decode."""
    line = "data: " + json.dumps({"type": "chunk", "data": ""})
    assert tts._parse_sse_audio_chunk(line) is None
