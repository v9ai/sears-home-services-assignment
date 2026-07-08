"""Offline tests for `app.agent.tts_cache` (latency-engineering P0-1)."""

from __future__ import annotations

import hashlib

import pytest

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


async def test_different_response_formats_get_distinct_cache_files(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tts_cache.tts, "synthesize", _fake_synthesize_factory([b"ab"]))

    await _drain(tts_cache.synthesize_cached(PHONE_TOOL_FILLER, response_format="mp3"))
    await _drain(tts_cache.synthesize_cached(PHONE_TOOL_FILLER, response_format="pcm"))

    assert tts_cache.cache_path(PHONE_TOOL_FILLER, "mp3").exists()
    assert tts_cache.cache_path(PHONE_TOOL_FILLER, "pcm").exists()
