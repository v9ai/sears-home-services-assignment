"""Offline tests for `app.agent.tts_cache` (latency-engineering P0-1)."""

from __future__ import annotations

import hashlib

from app.agent import tts_cache
from app.agent.fillers import PHONE_TOOL_FILLER


async def _drain(agen):
    return [chunk async for chunk in agen]


def _fake_synthesize_factory(chunks: list[bytes], spy: list[str] | None = None):
    async def _fake_synthesize(text, **kwargs):
        if spy is not None:
            spy.append(text)
        for chunk in chunks:
            yield chunk

    return _fake_synthesize


async def test_cache_miss_writes_file_and_streams_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tts_cache.tts, "synthesize", _fake_synthesize_factory([b"ab", b"cd"]))

    chunks = await _drain(tts_cache.synthesize_cached(PHONE_TOOL_FILLER, response_format="mp3"))

    assert chunks == [b"ab", b"cd"]
    path = tts_cache.cache_path(PHONE_TOOL_FILLER, "mp3")
    assert path.exists()
    assert path.read_bytes() == b"abcd"


async def test_cache_hit_skips_live_synthesize(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    path = tts_cache.cache_path(PHONE_TOOL_FILLER, "mp3")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"cached-bytes")

    async def _fail_synthesize(text, **kwargs):
        raise AssertionError("must not call live synthesize on a cache hit")
        yield b""  # pragma: no cover - unreachable, keeps this an async generator

    monkeypatch.setattr(tts_cache.tts, "synthesize", _fail_synthesize)

    chunks = await _drain(tts_cache.synthesize_cached(PHONE_TOOL_FILLER, response_format="mp3"))

    assert chunks == [b"cached-bytes"]


async def test_noncached_text_passthrough_no_disk_write(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    spy: list[str] = []
    monkeypatch.setattr(tts_cache.tts, "synthesize", _fake_synthesize_factory([b"xy"], spy))

    chunks = await _drain(tts_cache.synthesize_cached("an ordinary LLM sentence"))

    assert chunks == [b"xy"]
    assert spy == ["an ordinary LLM sentence"]
    assert list(tmp_path.iterdir()) == []


async def test_cache_write_failure_is_swallowed_and_logged(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tts_cache.tts, "synthesize", _fake_synthesize_factory([b"ab"]))

    def _boom(self, data):
        raise OSError("disk full")

    monkeypatch.setattr(tts_cache.Path, "write_bytes", _boom)

    with caplog.at_level("ERROR", logger="app.agent.tts_cache"):
        chunks = await _drain(tts_cache.synthesize_cached(PHONE_TOOL_FILLER, response_format="mp3"))

    assert chunks == [b"ab"]
    assert any("tts_cache_write_failed" in r.message for r in caplog.records)


def test_cache_path_is_sha1_of_text(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    digest = hashlib.sha1(PHONE_TOOL_FILLER.encode()).hexdigest()

    path = tts_cache.cache_path(PHONE_TOOL_FILLER, "pcm")

    assert path == tmp_path / f"{digest}.pcm"


def test_default_voice_keeps_the_historical_text_only_key(tmp_path, monkeypatch):
    """Backward-compat (task #13 fix): the default voice must keep the text-only key so
    entries already on disk stay valid — the explicit default equals the implicit one."""
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    assert tts_cache.cache_path(PHONE_TOOL_FILLER, "pcm") == tts_cache.cache_path(
        PHONE_TOOL_FILLER, "pcm", voice=tts_cache.DEFAULT_VOICE
    )


def test_nondefault_voice_gets_a_distinct_key(tmp_path, monkeypatch):
    """A non-default voice folds into the cache key, so it can never collide with the
    default voice's file for the same string/format."""
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    default_path = tts_cache.cache_path(PHONE_TOOL_FILLER, "pcm")
    other_path = tts_cache.cache_path(PHONE_TOOL_FILLER, "pcm", voice="echo")

    assert other_path != default_path
    assert other_path.suffix == ".pcm"  # format still the on-disk extension


async def test_different_response_formats_get_distinct_cache_files(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tts_cache.tts, "synthesize", _fake_synthesize_factory([b"ab"]))

    await _drain(tts_cache.synthesize_cached(PHONE_TOOL_FILLER, response_format="mp3"))
    await _drain(tts_cache.synthesize_cached(PHONE_TOOL_FILLER, response_format="pcm"))

    assert tts_cache.cache_path(PHONE_TOOL_FILLER, "mp3").exists()
    assert tts_cache.cache_path(PHONE_TOOL_FILLER, "pcm").exists()


async def test_cache_hit_yields_whole_file_as_single_chunk(monkeypatch, tmp_path):
    """A hit reads the file in one shot (not re-chunked): one yield of the full bytes,
    distinct from the miss path that streams the provider's chunk boundaries."""
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    path = tts_cache.cache_path(PHONE_TOOL_FILLER, "mp3")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"one-two-three")

    async def _fail(text, **kwargs):
        raise AssertionError("hit must not synthesize")
        yield b""  # pragma: no cover

    monkeypatch.setattr(tts_cache.tts, "synthesize", _fail)

    chunks = await _drain(tts_cache.synthesize_cached(PHONE_TOOL_FILLER, response_format="mp3"))

    assert chunks == [b"one-two-three"]  # exactly one chunk


# --- voice passthrough --------------------------------------------------------------------


async def test_voice_is_forwarded_to_synthesize_on_passthrough(monkeypatch, tmp_path):
    """Non-cached text passes the caller's `voice` straight through to the provider."""
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    seen: dict = {}

    async def _spy(text, *, voice="alloy", response_format="mp3"):
        seen["voice"] = voice
        yield b"x"

    monkeypatch.setattr(tts_cache.tts, "synthesize", _spy)

    await _drain(tts_cache.synthesize_cached("ordinary sentence", voice="echo"))

    assert seen["voice"] == "echo"


async def test_voice_is_forwarded_on_cold_cache_miss(monkeypatch, tmp_path):
    """A cached string on a cold cache still synthesizes with the requested voice."""
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    seen: dict = {}

    async def _spy(text, *, voice="alloy", response_format="mp3"):
        seen["voice"] = voice
        yield b"x"

    monkeypatch.setattr(tts_cache.tts, "synthesize", _spy)

    await _drain(
        tts_cache.synthesize_cached(PHONE_TOOL_FILLER, voice="shimmer", response_format="pcm")
    )

    assert seen["voice"] == "shimmer"


async def test_distinct_voices_get_distinct_cache_files(monkeypatch, tmp_path):
    """Two voices for the same cached string must not collide on disk — the second voice
    gets its own audio, not the first voice's cached file (task #13 fix)."""
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)

    async def _alloy(text, *, voice="alloy", response_format="mp3"):
        yield b"ALLOY-AUDIO"

    monkeypatch.setattr(tts_cache.tts, "synthesize", _alloy)
    first = await _drain(
        tts_cache.synthesize_cached(PHONE_TOOL_FILLER, voice="alloy", response_format="pcm")
    )

    async def _echo(text, *, voice="alloy", response_format="mp3"):
        yield b"ECHO-AUDIO"

    monkeypatch.setattr(tts_cache.tts, "synthesize", _echo)
    second = await _drain(
        tts_cache.synthesize_cached(PHONE_TOOL_FILLER, voice="echo", response_format="pcm")
    )

    assert first == [b"ALLOY-AUDIO"]
    assert second == [b"ECHO-AUDIO"]  # its own file, not the cached ALLOY-AUDIO


# --- prewarm ------------------------------------------------------------------------------


async def test_prewarm_noop_without_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    # prewarm gates per-format on the provider synthesize would actually use
    # (B3), so a true no-op needs every provider's env absent, not just OpenAI's.
    for key in ("OPENAI_API_KEY", "CARTESIA_API_KEY", "CARTESIA_VOICE_ID", "WEB_TTS_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    called = False

    async def _spy(text, **kwargs):
        nonlocal called
        called = True
        yield b"x"

    monkeypatch.setattr(tts_cache.tts, "synthesize", _spy)

    await tts_cache.prewarm()

    assert called is False
    assert list(tmp_path.iterdir()) == []


async def test_prewarm_synthesizes_and_writes_every_cached_string(monkeypatch, tmp_path):
    from app.agent.fillers import CACHED_STRINGS

    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    synthesized: list[str] = []

    async def _spy(text, *, voice="alloy", response_format="mp3"):
        synthesized.append(text)
        yield b"audio"

    monkeypatch.setattr(tts_cache.tts, "synthesize", _spy)

    await tts_cache.prewarm(formats=("pcm",))

    assert sorted(synthesized) == sorted(CACHED_STRINGS)
    for text in CACHED_STRINGS:
        assert tts_cache.cache_path(text, "pcm").exists()


async def test_prewarm_skips_already_cached_files(monkeypatch, tmp_path):
    from app.agent.fillers import CACHED_STRINGS

    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    # Pre-seed one cached string so prewarm must skip it.
    seeded = CACHED_STRINGS[0]
    p = tts_cache.cache_path(seeded, "pcm")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"already-warm")
    synthesized: list[str] = []

    async def _spy(text, *, voice="alloy", response_format="mp3"):
        synthesized.append(text)
        yield b"audio"

    monkeypatch.setattr(tts_cache.tts, "synthesize", _spy)

    await tts_cache.prewarm(formats=("pcm",))

    assert seeded not in synthesized  # skipped
    assert p.read_bytes() == b"already-warm"  # untouched


async def test_prewarm_swallows_synthesis_error(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def _boom(text, **kwargs):
        raise RuntimeError("provider down")
        yield b""  # pragma: no cover

    monkeypatch.setattr(tts_cache.tts, "synthesize", _boom)

    with caplog.at_level("ERROR", logger="app.agent.tts_cache"):
        await tts_cache.prewarm(formats=("pcm",))  # must not raise

    assert any("tts_cache_prewarm_failed" in r.message for r in caplog.records)
