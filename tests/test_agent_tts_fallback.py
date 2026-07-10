"""Provider-internals + error/routing coverage for `app/agent/tts.py` (round 3, task #32).

The sibling `tests/test_web_tts_provider.py` pins provider *dispatch* by stubbing the
whole `_synthesize_cartesia` function and by only hitting the OpenAI branch to prove it
*raises* on a missing key — so the real streaming internals stay uncovered. This file
fills exactly those gaps by faking the transports (httpx for Cartesia's SSE, the
AsyncOpenAI client for OpenAI) so the actual code paths run:

- the Cartesia SSE request/stream/`raise_for_status`/`aiter_lines`/parse-and-yield loop
  (tts.py lines ~78-94), including HTTP-error propagation, and
- the OpenAI `with_streaming_response` / `iter_bytes` loop with its empty-chunk skip
  (tts.py lines ~113-124).

Latency-relevant invariant pinned throughout: exactly ONE provider transport is
constructed per call — the chosen path never also spins up the other (no double
synthesis), and an error propagates loudly rather than degrading to silent no-audio.

No network, no API keys: every provider transport is a fake.
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from app.agent import tts


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Neutral env + a cleared _client cache so each test's provider routing is deterministic.
    for key in (
        "WEB_TTS_PROVIDER",
        "CARTESIA_API_KEY",
        "CARTESIA_VOICE_ID",
        "CARTESIA_TTS_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_TTS_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    # Clear only at setup: tests monkeypatch tts._client, and monkeypatch reverts it after
    # the test (after this fixture's teardown), so a post-yield cache_clear would hit the
    # still-patched lambda. The next test's setup clears the restored real cache.
    tts._client.cache_clear()
    yield


# --- fakes -----------------------------------------------------------------------------


def _install_fake_httpx(monkeypatch, *, lines=(), raise_exc=None):
    """Replace httpx.AsyncClient with a fake whose streamed response yields `lines`
    (and optionally raises `raise_exc` from raise_for_status). Returns a recorder dict
    capturing the stream() call args."""
    recorder: dict = {"stream_calls": 0}

    class _FakeStreamCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def raise_for_status(self):
            if raise_exc is not None:
                raise raise_exc

        async def aiter_lines(self):
            for line in lines:
                yield line

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            recorder["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, *, json=None, headers=None):
            recorder["stream_calls"] += 1
            recorder["method"] = method
            recorder["url"] = url
            recorder["body"] = json
            recorder["headers"] = headers
            return _FakeStreamCtx()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return recorder


def _install_fake_openai(monkeypatch, *, chunks=()):
    """Point tts._client at a fake AsyncOpenAI whose speech stream yields `chunks`.
    Returns a recorder dict capturing the create() kwargs."""
    recorder: dict = {"create_calls": 0}

    class _FakeSpeechResp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def iter_bytes(self):
            for chunk in chunks:
                yield chunk

    class _FakeWithStreaming:
        def create(self, **kwargs):
            recorder["create_calls"] += 1
            recorder["create_kwargs"] = kwargs
            return _FakeSpeechResp()

    client = SimpleNamespace(
        audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=_FakeWithStreaming()))
    )
    monkeypatch.setattr(tts, "_client", lambda: client)
    return recorder


def _boom(*args, **kwargs):
    raise AssertionError("the other provider transport must not be constructed (double synthesis)")


def _sse_chunk(audio: bytes) -> str:
    return "data: " + json.dumps({"type": "chunk", "data": base64.b64encode(audio).decode()})


async def _collect(response_format="pcm", **kwargs):
    stream = tts.synthesize("hello there", response_format=response_format, **kwargs)
    return [chunk async for chunk in stream]


# --- Cartesia SSE internals (tts.py ~78-94) --------------------------------------------


async def test_cartesia_streams_and_parses_real_sse(monkeypatch):
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "v")
    audio1, audio2 = b"\x10\x20\x30", b"\x40\x50"
    recorder = _install_fake_httpx(
        monkeypatch,
        lines=[
            _sse_chunk(audio1),
            ": keepalive",  # SSE comment — ignored
            _sse_chunk(audio2),
            "data: " + json.dumps({"type": "done"}),  # terminal — ignored
        ],
    )
    # If the code ever also built the OpenAI client, that's a double-synthesis bug.
    monkeypatch.setattr(tts, "_client", _boom)

    got = await _collect(response_format="pcm")

    assert got == [audio1, audio2]  # real aiter_lines + _parse_sse_audio_chunk loop ran
    assert recorder["stream_calls"] == 1  # exactly one transport, no retry/double synth


async def test_cartesia_request_carries_expected_headers_and_body(monkeypatch):
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "secret-key")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "voice-123")
    recorder = _install_fake_httpx(monkeypatch, lines=[_sse_chunk(b"\x01")])

    await _collect(response_format="pcm")

    assert recorder["method"] == "POST"
    assert recorder["url"] == tts.CARTESIA_TTS_SSE_URL
    assert recorder["headers"] == {
        "X-API-Key": "secret-key",
        "Cartesia-Version": tts.CARTESIA_VERSION,
    }
    body = recorder["body"]
    assert body["transcript"] == "hello there"
    assert body["voice"] == {"mode": "id", "id": "voice-123"}
    assert body["output_format"] == tts._CARTESIA_OUTPUT_FORMATS["pcm"]
    assert body["language"] == "en"
    assert body["model_id"] == "sonic-3.5"  # default when CARTESIA_TTS_MODEL unset


async def test_cartesia_model_env_overrides_body(monkeypatch):
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "v")
    monkeypatch.setenv("CARTESIA_TTS_MODEL", "sonic-turbo")
    recorder = _install_fake_httpx(monkeypatch, lines=[_sse_chunk(b"\x01")])

    await _collect(response_format="pcm")

    assert recorder["body"]["model_id"] == "sonic-turbo"


async def test_cartesia_http_error_propagates_and_does_not_fail_over(monkeypatch):
    """A Cartesia HTTP error (raise_for_status) must surface, never degrade to silent
    no-audio, and must NOT silently retry through OpenAI — the code fails loud, it does
    not cross-provider fail over."""
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "v")
    error = RuntimeError("cartesia HTTP 502")
    _install_fake_httpx(monkeypatch, lines=[_sse_chunk(b"\x01")], raise_exc=error)
    monkeypatch.setattr(tts, "_client", _boom)  # no failover to OpenAI

    collected = []
    with pytest.raises(RuntimeError, match="cartesia HTTP 502"):
        async for chunk in tts.synthesize("hello there", response_format="pcm"):
            collected.append(chunk)

    assert collected == []  # error raised before any audio — not a silent empty stream


# --- OpenAI streaming internals (tts.py ~113-124) --------------------------------------


async def test_openai_branch_streams_iter_bytes_chunks(monkeypatch):
    monkeypatch.setenv("WEB_TTS_PROVIDER", "openai")  # opt out of cartesia even for pcm
    recorder = _install_fake_openai(monkeypatch, chunks=[b"aa", b"bb", b"cc"])

    got = [c async for c in tts.synthesize("hi there", voice="verse", response_format="pcm")]

    assert got == [b"aa", b"bb", b"cc"]
    kwargs = recorder["create_kwargs"]
    assert kwargs["model"] == "gpt-4o-mini-tts"  # default when OPENAI_TTS_MODEL unset
    assert kwargs["voice"] == "verse"
    assert kwargs["input"] == "hi there"
    assert kwargs["response_format"] == "pcm"
    assert kwargs["instructions"] == tts.WARM_VOICE_INSTRUCTIONS


async def test_openai_branch_skips_empty_chunks(monkeypatch):
    # The `if chunk:` guard (line ~123) drops keepalive/empty frames so downstream
    # framing never sees a zero-length buffer.
    monkeypatch.setenv("WEB_TTS_PROVIDER", "openai")
    _install_fake_openai(monkeypatch, chunks=[b"a", b"", b"c", b""])

    got = [c async for c in tts.synthesize("hi", response_format="pcm")]

    assert got == [b"a", b"c"]


async def test_openai_model_env_override_in_create(monkeypatch):
    monkeypatch.setenv("WEB_TTS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts-preview")
    recorder = _install_fake_openai(monkeypatch, chunks=[b"a"])

    await _collect(response_format="pcm")

    assert recorder["create_kwargs"]["model"] == "gpt-4o-mini-tts-preview"


async def test_mp3_streams_through_openai_iter_bytes(monkeypatch):
    """Format routing: mp3 always takes the OpenAI branch (Cartesia SSE 400s on mp3),
    and it must actually STREAM audio there — the sibling test only proved it raises on
    a missing key. httpx must never be constructed for the mp3 path."""
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")  # default; mp3 still bypasses it
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "v")
    recorder = _install_fake_openai(monkeypatch, chunks=[b"m1", b"m2"])
    monkeypatch.setattr(httpx, "AsyncClient", _boom)  # cartesia transport must stay untouched

    got = [c async for c in tts.synthesize("hello", response_format="mp3")]

    assert got == [b"m1", b"m2"]
    assert recorder["create_kwargs"]["response_format"] == "mp3"


# --- no double-synthesis (latency) -----------------------------------------------------


async def test_openai_path_never_constructs_httpx(monkeypatch):
    monkeypatch.setenv("WEB_TTS_PROVIDER", "openai")
    _install_fake_openai(monkeypatch, chunks=[b"a"])
    monkeypatch.setattr(httpx, "AsyncClient", _boom)  # Cartesia transport must not spin up

    got = [c async for c in tts.synthesize("hi", response_format="pcm")]

    assert got == [b"a"]


async def test_cartesia_path_never_constructs_openai_client(monkeypatch):
    monkeypatch.setenv("WEB_TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "v")
    _install_fake_httpx(monkeypatch, lines=[_sse_chunk(b"\x09")])
    monkeypatch.setattr(tts, "_client", _boom)  # OpenAI client must not be built

    got = await _collect(response_format="pcm")

    assert got == [b"\x09"]
