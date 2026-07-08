"""Channel-level latency regression guards: cache hits, eos-filler timing, async IO,
first-clause chunking, and the prose-before-tools prompt assert. Fake-based, no
network, no database (background persist failures are logged-and-swallowed by design).
"""

from __future__ import annotations

import asyncio
import itertools
import time
import uuid

import pytest

import app.agent.tts_cache as tts_cache
import app.ws.routes as ws_routes
from app.agent.pipeline import split_ready_sentences
from app.agent.prompts import GREETING, build_system_prompt
from app.agent.session_store import SessionState
from app.contracts import CaseFile


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[tuple[float, dict]] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append((time.monotonic(), data))


def make_state() -> SessionState:
    from llama_index.core.memory import ChatMemoryBuffer

    from tests.fakes import FakeFunctionCallingLLM

    return SessionState(
        session_id=uuid.uuid4(),
        case_file=CaseFile(),
        memory=ChatMemoryBuffer.from_defaults(llm=FakeFunctionCallingLLM([])),
        transcript=[],
        is_new=True,
    )


async def test_constant_lines_never_hit_tts_api(tmp_path, monkeypatch):
    """O1 guard: warm-cache playback of a cached string performs ZERO API calls."""
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    api_calls: list[str] = []

    async def fake_api_synth(text: str, **kwargs):
        api_calls.append(text)
        yield b"fake-audio"

    monkeypatch.setattr(tts_cache.tts, "synthesize", fake_api_synth)

    async for _ in tts_cache.synthesize_cached(GREETING, response_format="pcm"):
        pass
    assert api_calls == [GREETING]  # cold: exactly one API call, writes the file
    async for chunk in tts_cache.synthesize_cached(GREETING, response_format="pcm"):
        assert chunk == b"fake-audio"
    assert api_calls == [GREETING], "warm cache still hit the TTS API — O1 regression"


async def test_cache_filename_embeds_text_hash(tmp_path, monkeypatch):
    """Changing the constant's text must miss the old cache (no stale audio)."""
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    a = tts_cache.cache_path("hello", "pcm")
    b = tts_cache.cache_path("hello!", "pcm")
    assert a != b


async def test_filler_beats_slow_llm(monkeypatch, tmp_path):
    """O2 guard: with an 800 ms-TTFT agent, filler audio must be emitted well before
    the first agent event — the caller never sits in silence."""
    monkeypatch.setattr(ws_routes, "RECORDINGS_DIR", str(tmp_path))
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)

    async def fake_synth(text: str, **kwargs):
        yield b"a" * 8

    monkeypatch.setattr(tts_cache.tts, "synthesize", fake_synth)

    async def slow_run_turn(*args, **kwargs):
        await asyncio.sleep(0.8)
        from app.agent.core import TurnComplete

        yield TurnComplete(full_text="")

    monkeypatch.setattr(ws_routes, "run_turn", slow_run_turn)
    ws = FakeWS()
    state = make_state()
    t0 = time.monotonic()
    await ws_routes._handle_user_text(
        ws, state, "my washer is broken", itertools.count(1), itertools.count(1)
    )
    audio_times = [t for t, f in ws.sent if f.get("type") == "audio"]
    assert audio_times, "no audio emitted at all"
    first_audio = audio_times[0] - t0
    assert first_audio < 0.4, f"filler took {first_audio:.2f}s — eos-filler regression"


async def test_persist_off_critical_path(monkeypatch, tmp_path):
    """O4 guard: the turn must complete without awaiting persistence; persistence
    still lands afterwards."""
    monkeypatch.setattr(ws_routes, "RECORDINGS_DIR", str(tmp_path))
    monkeypatch.setattr(tts_cache, "CACHE_DIR", tmp_path)
    persisted = asyncio.Event()

    async def slow_persist(db, state):
        await asyncio.sleep(0.5)
        persisted.set()

    class FakeSessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(ws_routes, "persist_session", slow_persist)
    monkeypatch.setattr(ws_routes, "get_sessionmaker", lambda: lambda: FakeSessionCtx())

    async def fake_synth(text: str, **kwargs):
        yield b"a"

    monkeypatch.setattr(tts_cache.tts, "synthesize", fake_synth)

    async def quick_run_turn(*args, **kwargs):
        from app.agent.core import SentenceReady, TurnComplete

        yield SentenceReady(text="All set.")
        yield TurnComplete(full_text="All set.")

    monkeypatch.setattr(ws_routes, "run_turn", quick_run_turn)
    ws = FakeWS()
    state = make_state()
    t0 = time.monotonic()
    await ws_routes._handle_user_text(ws, state, "thanks", itertools.count(1), itertools.count(1))
    handler_wall = time.monotonic() - t0
    assert handler_wall < 0.45, f"turn waited on persistence ({handler_wall:.2f}s) — O4 regression"
    assert not persisted.is_set()
    await asyncio.wait_for(persisted.wait(), timeout=2)  # still lands


def test_first_clause_chunker():
    """O6 unit: first emission may break at a clause; no text lost."""
    buf = "Thanks for letting me know about the washer, that grinding sound"
    sentences, rest = split_ready_sentences(buf, first_emission=True)
    assert sentences == ["Thanks for letting me know about the washer,"]
    assert rest == "that grinding sound"
    # not first emission: clause break must NOT fire
    sentences2, rest2 = split_ready_sentences(buf, first_emission=False)
    assert sentences2 == [] and rest2 == buf
    # short buffers never clause-break
    s3, r3 = split_ready_sentences("Well, ok", first_emission=True)
    assert s3 == [] and r3 == "Well, ok"


def test_prompt_prose_before_tools_and_length_cap():
    """P0-4 + O8 static asserts on the live system prompt."""
    prompt = build_system_prompt(CaseFile())
    assert "BEFORE calling them" in prompt
    assert "AT MOST three short sentences" in prompt


def test_prompt_case_file_json_is_compact():
    """P1-2 (cost fix): the case-file JSON section must not be pretty-printed."""
    case_file = CaseFile(appliance_type="washer")
    prompt = build_system_prompt(case_file)
    compact = case_file.model_dump_json()
    pretty = case_file.model_dump_json(indent=2)
    assert compact in prompt
    assert pretty not in prompt


@pytest.fixture(autouse=True)
def _reset_cache_dir():
    yield
