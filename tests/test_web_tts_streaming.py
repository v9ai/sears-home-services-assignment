"""Web TTS provider I/O edges (bugfix-loop T18, audit02 gaps 2/4/6).

Every existing test monkeypatches `_synthesize_cartesia` away and stops the
OpenAI branch at its missing-key raise — the real streaming loops had zero
coverage. Cartesia is driven here through a genuine httpx MockTransport
(request shape, SSE ordering, error status); the OpenAI branch through a fake
streaming-response client (kwargs forwarding, chunk iteration).
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

import app.agent.tts as tts
from app.agent.tts import WARM_VOICE_INSTRUCTIONS, synthesize

B64_ONE = base64.b64encode(b"audio-one").decode()
B64_TWO = base64.b64encode(b"audio-two").decode()


def _sse(*events: dict) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n" for e in events).encode()


@pytest.fixture
def cartesia_env(monkeypatch):
    monkeypatch.delenv("WEB_TTS_PROVIDER", raising=False)  # default: cartesia
    monkeypatch.setenv("CARTESIA_API_KEY", "ck-test")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "voice-123")
    monkeypatch.delenv("CARTESIA_TTS_MODEL", raising=False)


def _mock_cartesia(monkeypatch, responder):
    """Route the function's inline httpx.AsyncClient through a MockTransport."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return responder(request)

    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    return captured


async def test_cartesia_streams_chunks_in_order_and_stops_at_done(
    cartesia_env, monkeypatch
) -> None:
    body = _sse(
        {"type": "chunk", "data": B64_ONE},
        {"type": "chunk", "data": B64_TWO},
        {"type": "done"},
    )
    captured = _mock_cartesia(monkeypatch, lambda req: httpx.Response(200, content=body))

    chunks = [c async for c in synthesize("hello there", response_format="pcm")]
    assert chunks == [b"audio-one", b"audio-two"]

    request = captured[0]
    assert request.headers["x-api-key"] == "ck-test"
    assert request.headers["cartesia-version"] == tts.CARTESIA_VERSION
    payload = json.loads(request.content)
    assert payload["transcript"] == "hello there"
    assert payload["voice"] == {"mode": "id", "id": "voice-123"}
    assert payload["output_format"]["encoding"] == "pcm_s16le"
    assert payload["model_id"] == "sonic-3.5"
    assert payload["language"] == "en"


async def test_cartesia_http_error_raises_before_yielding(cartesia_env, monkeypatch) -> None:
    _mock_cartesia(monkeypatch, lambda req: httpx.Response(400, content=b"bad request"))
    with pytest.raises(httpx.HTTPStatusError):
        [c async for c in synthesize("hello", response_format="pcm")]


async def test_cartesia_ignores_keepalives_and_chunks_without_data(
    cartesia_env, monkeypatch
) -> None:
    body = (
        b": keepalive comment\n"
        + _sse({"type": "chunk"})  # chunk event missing its data key
        + b"data: {not json\n"
        + _sse({"type": "chunk", "data": B64_ONE}, {"type": "done"})
    )
    _mock_cartesia(monkeypatch, lambda req: httpx.Response(200, content=body))
    chunks = [c async for c in synthesize("hello", response_format="pcm")]
    assert chunks == [b"audio-one"]


# --- OpenAI streaming branch ---------------------------------------------------------


class _FakeStreamingResponse:
    def __init__(self, recorder: dict, **kwargs) -> None:
        recorder.update(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def iter_bytes(self):
        yield b"mp3-one"
        yield b""  # empty chunks must be skipped
        yield b"mp3-two"


async def test_openai_branch_forwards_voice_and_instructions(monkeypatch) -> None:
    recorded: dict = {}

    class _FakeSpeech:
        def create(self, **kwargs):
            return _FakeStreamingResponse(recorded, **kwargs)

    class _FakeClient:
        class audio:  # noqa: N801 — mirrors the SDK attribute chain
            class speech:  # noqa: N801
                with_streaming_response = _FakeSpeech()

    monkeypatch.setenv("WEB_TTS_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_TTS_MODEL", raising=False)
    monkeypatch.setattr(tts, "_client", lambda: _FakeClient())

    chunks = [c async for c in synthesize("read this", voice="echo", response_format="pcm")]
    assert chunks == [b"mp3-one", b"mp3-two"]
    assert recorded["model"] == "gpt-4o-mini-tts"
    assert recorded["voice"] == "echo"
    assert recorded["input"] == "read this"
    assert recorded["response_format"] == "pcm"
    assert recorded["instructions"] == WARM_VOICE_INSTRUCTIONS


async def test_mp3_falls_through_to_openai_even_under_cartesia(cartesia_env, monkeypatch) -> None:
    recorded: dict = {}

    class _FakeSpeech:
        def create(self, **kwargs):
            return _FakeStreamingResponse(recorded, **kwargs)

    class _FakeClient:
        class audio:  # noqa: N801
            class speech:  # noqa: N801
                with_streaming_response = _FakeSpeech()

    monkeypatch.setattr(tts, "_client", lambda: _FakeClient())
    chunks = [c async for c in synthesize("legacy blob", response_format="mp3")]
    assert chunks == [b"mp3-one", b"mp3-two"]
    assert recorded["response_format"] == "mp3"
