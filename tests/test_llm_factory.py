"""`get_llm()` provider branches (2026-07-08-deepseek-agent-llm spec).

No network: only constructs LLM objects and asserts their configuration. The factory is
lru_cached, so every case clears the cache before and after mutating the env.
"""

import logging

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


def test_deepseek_reasoner_variant_suffix_is_also_rejected(monkeypatch):
    """The guard is a prefix check (`startswith`), so a versioned reasoner id must be
    rejected too — not just the bare `deepseek-reasoner` string."""
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner-lite")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-real")

    with pytest.raises(ValueError, match="function calling"):
        get_llm()


def test_unknown_provider_falls_through_to_deepseek_default(monkeypatch):
    """Only `openai` diverts from the default; any other value (typo, unsupported vendor)
    resolves to the DeepSeek default rather than erroring on an unknown provider."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-real")

    assert type(get_llm()).__name__ == "DeepSeek"


def test_deepseek_provider_is_case_and_whitespace_normalized(monkeypatch):
    """Same normalization the openai branch gets — `"  DeepSeek  "` resolves to DeepSeek,
    not an unknown-provider fallthrough that happens to land there by accident."""
    monkeypatch.setenv("LLM_PROVIDER", "  DeepSeek  ")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-real")

    assert type(get_llm()).__name__ == "DeepSeek"


def test_openai_branch_does_not_require_a_deepseek_key(monkeypatch):
    """Selecting OpenAI must not transitively demand DEEPSEEK_API_KEY — the two provider
    branches are independent (a demo-day machine may carry only one key)."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")

    assert type(get_llm()).__name__ == "OpenAI"


def test_factory_is_lru_cached_returns_same_instance(monkeypatch):
    """`get_llm` is `@lru_cache(maxsize=1)`: repeated calls with the same env return the
    identical object (one LLM client per process), and cache_clear resets that."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-real")

    first = get_llm()
    assert get_llm() is first

    get_llm.cache_clear()
    assert get_llm() is not first


def test_factory_does_not_log_the_api_key(monkeypatch, caplog):
    """Constructing the LLM must not emit the key into any log record. The app never logs
    the raw LLM object today (instrumentation logs only timing/usage); this pins that so a
    future debug line printing the provider config can't quietly leak the secret."""
    secret = "sk-should-never-be-logged-DEADBEEF"
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    with caplog.at_level(logging.DEBUG):
        get_llm()

    assert secret not in caplog.text


@pytest.mark.parametrize(
    ("provider_env", "key_env"),
    [
        ({}, "DEEPSEEK_API_KEY"),  # default DeepSeek path
        ({"LLM_PROVIDER": "openai"}, "OPENAI_API_KEY"),  # OpenAI fallback path
    ],
)
def test_llm_object_serialization_never_exposes_api_key(monkeypatch, provider_env, key_env):
    """The factory's LLM objects must redact the key on every serialization surface — repr,
    str, model_dump, model_dump_json — since those are how an object reaches a log line,
    a trace, or an exception message (task #12 fix, app/agent/core.py)."""
    secret = "sk-secret-should-be-redacted-DEADBEEF"
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    for name, value in provider_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(key_env, secret)

    llm = get_llm()

    assert secret not in repr(llm)
    assert secret not in str(llm)
    assert secret not in str(llm.model_dump())
    assert secret not in llm.model_dump_json()


def test_redaction_does_not_break_the_real_client_credential(monkeypatch):
    """The redaction must be display-only: the client still needs the REAL key to make
    calls. If a future change achieved redaction by scrubbing the stored key, real API
    calls would silently break — so pin that the credential path still yields the secret."""
    secret = "sk-secret-still-usable-DEADBEEF"
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    llm = get_llm()

    # The client reads the credential from these, not from repr/model_dump.
    assert llm.api_key == secret
    assert secret in str(llm._get_credential_kwargs())
