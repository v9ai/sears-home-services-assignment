"""`get_llm()` provider branches (2026-07-08-deepseek-agent-llm spec).

No network: only constructs LLM objects and asserts their configuration. The factory is
lru_cached, so every case clears the cache before and after mutating the env.
"""

import pytest
from llama_index.core.llms.function_calling import FunctionCallingLLM

from app.agent.core import get_llm


@pytest.fixture(autouse=True)
def _clear_llm_cache():
    get_llm.cache_clear()
    yield
    get_llm.cache_clear()


def test_default_provider_is_deepseek_chat_function_calling(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-real")

    llm = get_llm()

    assert type(llm).__name__ == "DeepSeek"
    assert isinstance(llm, FunctionCallingLLM)
    assert llm.metadata.is_function_calling_model
    assert llm.metadata.model_name == "deepseek-chat"


def test_deepseek_model_env_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat-v3")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-real")

    assert get_llm().metadata.model_name == "deepseek-chat-v3"


def test_deepseek_requires_api_key(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(KeyError):
        get_llm()


def test_openai_fallback_branch(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")

    llm = get_llm()

    assert type(llm).__name__ == "OpenAI"
    assert isinstance(llm, FunctionCallingLLM)
    assert llm.metadata.model_name == "gpt-4o"


def test_openai_model_env_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_LLM_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")

    assert get_llm().metadata.model_name == "gpt-4.1-mini"


def test_provider_is_normalized_like_the_voice_factory(monkeypatch):
    """Regression: `LLM_PROVIDER="  OpenAI  "` used to select OpenAI in the voice pipeline
    (app/voice/bot.py normalizes) but silently fall through to DeepSeek here — the two LLM
    stacks must resolve the same provider from the same env value."""
    monkeypatch.setenv("LLM_PROVIDER", "  OpenAI  ")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")

    assert type(get_llm()).__name__ == "OpenAI"


def test_deepseek_reasoner_is_rejected_fail_fast(monkeypatch):
    """deepseek-reasoner has no function calling (the tool loop requires it) — the factory
    must raise at build time, not fail confusingly mid-turn (.env.example:6)."""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-real")

    with pytest.raises(ValueError, match="function calling"):
        get_llm()
