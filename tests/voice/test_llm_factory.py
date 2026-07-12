"""LLM-specific tests for the voice pipeline: the `_build_llm` provider/model factory
(`app/voice/bot.py`) and the function-calling wiring in `_build_conversation_pipeline`.

Mirrors `tests/voice/test_tts_sample_rate.py`'s provider-selection style. All hermetic —
constructing a service builds a lazy client but makes no network call, and the tool-registration
test drives the real pipeline builder with fake services.
"""

from __future__ import annotations

import pytest

pipecat_frames = pytest.importorskip("pipecat.frames.frames")

from app.voice.bot import _build_conversation_pipeline, _build_llm  # noqa: E402
from app.voice.session import VoiceSession  # noqa: E402
from app.voice.tools import build_tools  # noqa: E402
from tests.voice.fakes import FakeLLM, FakeSTT, FakeTTS  # noqa: E402


# --- provider / model selection -----------------------------------------------------------
def test_llm_defaults_to_openai_gpt41_mini(monkeypatch):
    # f5 model-pin (loop-v2 i10): the code default is the P2-2 sweep winner, matching the
    # value .env has run live since 2026-07-10 — a deployment without VOICE_LLM_MODEL set
    # must not silently fall back to the slower gpt-4o (user-approved 2026-07-09).
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("VOICE_LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used-no-network-at-build")

    llm = _build_llm()
    assert type(llm).__name__ == "OpenAILLMService"
    assert llm._settings.model == "gpt-4.1-mini"


def test_voice_llm_model_override(monkeypatch):
    # VOICE_LLM_MODEL is decoupled from the LlamaIndex agent's OPENAI_LLM_MODEL — a change here
    # must NOT be shadowed by OPENAI_LLM_MODEL.
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.setenv("OPENAI_LLM_MODEL", "gpt-4.1-mini")  # the OTHER model var — must be ignored
    monkeypatch.setenv("VOICE_LLM_MODEL", "gpt-4o-mini")

    assert _build_llm()._settings.model == "gpt-4o-mini"


def test_llm_provider_deepseek_selects_deepseek(monkeypatch):
    pytest.importorskip("pipecat.services.deepseek.llm")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    llm = _build_llm()
    assert type(llm).__name__ == "DeepSeekLLMService"
    assert llm._settings.model == "deepseek-chat"


def test_deepseek_model_override(monkeypatch):
    pytest.importorskip("pipecat.services.deepseek.llm")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat-v3")

    assert _build_llm()._settings.model == "deepseek-chat-v3"


def test_deepseek_reasoner_is_rejected_fail_fast(monkeypatch):
    """deepseek-reasoner has no function calling (the voice tool loop requires it) — the
    factory must raise at build time, not fail confusingly mid-call (.env.example:6).
    Mirrors the agent-side guard test in tests/test_llm_factory.py."""
    pytest.importorskip("pipecat.services.deepseek.llm")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-used-no-network-at-build")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")

    with pytest.raises(ValueError, match="function calling"):
        _build_llm()


def test_llm_provider_is_case_insensitive(monkeypatch):
    pytest.importorskip("pipecat.services.deepseek.llm")
    monkeypatch.setenv("LLM_PROVIDER", "  DeepSeek  ")  # whitespace + mixed case
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-used-no-network-at-build")

    assert type(_build_llm()).__name__ == "DeepSeekLLMService"


# --- fail-fast on missing credentials -----------------------------------------------------
def test_llm_openai_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)  # default → openai
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(KeyError):
        _build_llm()


def test_llm_deepseek_missing_api_key_raises(monkeypatch):
    pytest.importorskip("pipecat.services.deepseek.llm")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(KeyError):
        _build_llm()


# --- function-calling wiring --------------------------------------------------------------
class _SpyLLM(FakeLLM):
    """Records every register_function() the pipeline builder makes, so the test can assert the
    LLM is wired to call the full ported toolset."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.registered: list[str] = []

    def register_function(self, function_name, handler, **kwargs):
        self.registered.append(function_name)
        return super().register_function(function_name, handler, **kwargs)


def test_all_ported_tools_registered_on_the_llm():
    session = VoiceSession.for_call("CAtest")
    expected = set(build_tools(session)[1])  # handler names — the ported app.tools.* functions
    assert expected  # sanity: there is a non-empty toolset to wire

    llm = _SpyLLM()
    _build_conversation_pipeline(session, FakeSTT(), llm, FakeTTS())

    assert set(llm.registered) == expected


def test_llm_context_seeded_with_system_prompt_and_tools_schema():
    """The LLM's function-calling surface: the context the pipeline hands the LLM must carry
    (a) exactly one system message — the case-file-current prompt — and (b) the full tools
    schema, so the model can actually *choose* the ported tools, not just have handlers
    registered for them."""
    from app.agent.prompts import build_system_prompt

    session = VoiceSession.for_call("CAtest")
    _, context, _, _ = _build_conversation_pipeline(session, FakeSTT(), FakeLLM(), FakeTTS())

    system_messages = [m for m in context.get_messages() if m.get("role") == "system"]
    assert len(system_messages) == 1
    assert system_messages[0]["content"] == build_system_prompt(session.case_file)

    schema_names = {f.name for f in context.tools.standard_tools}
    assert schema_names == set(build_tools(session)[1])
