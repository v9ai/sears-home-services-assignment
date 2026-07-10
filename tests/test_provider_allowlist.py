"""Static provider-allowlist guard (deepseek-agent-llm validation.md).

Fails when an OpenAI text-generation construction appears anywhere in ``app/``
outside the explicitly sanctioned sites. Sanctioned:

- ``app/agent/core.py`` — the ``LLM_PROVIDER=openai`` fallback branch of ``get_llm()``
  (tech-stack boundary amendment: shipped demo-day default).
- ``app/voice/bot.py`` — the Pipecat voice-channel LLM factory (``_build_llm``,
  provider-gated by ``LLM_PROVIDER``/``VOICE_LLM_MODEL``).
- ``app/vision/client.py`` — vision modality (OpenAI modality clients are allowed for
  vision/STT/TTS).
- ``app/latency_probe.py`` — diagnostic TTFT probe (latency-engineering spec), not an
  agent text-generation path.

A new match outside this list means someone wired OpenAI text generation into the
agent outside the sanctioned provider switch — exactly what the allowlist forbids.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

_TEXT_GEN_PATTERNS = (
    re.compile(r"llama_index\.llms\.openai"),
    re.compile(r"OpenAILLMService"),
    re.compile(r"chat\.completions"),
)

_ALLOWED = {
    "agent/core.py",
    "voice/bot.py",
    "vision/client.py",
    "latency_probe.py",
}


def _offending_files() -> set[str]:
    hits: set[str] = set()
    for path in APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in _TEXT_GEN_PATTERNS):
            hits.add(path.relative_to(APP_ROOT).as_posix())
    return hits


def test_openai_text_generation_only_in_sanctioned_sites():
    offending = _offending_files() - _ALLOWED
    assert not offending, (
        f"OpenAI text-generation construction found outside the provider allowlist: "
        f"{sorted(offending)} — route it through get_llm()'s LLM_PROVIDER switch or "
        f"amend the allowlist WITH a spec note (deepseek-agent-llm validation.md)."
    )


def test_allowlist_entries_still_exist():
    """A stale allowlist would quietly weaken the guard — every sanctioned file must
    still exist and still match (otherwise remove it from the list)."""
    present = _offending_files()
    stale = _ALLOWED - present
    assert not stale, f"Allowlist entries no longer match any OpenAI usage: {sorted(stale)}"


def test_allowlisted_files_exist_on_disk():
    """Every sanctioned path must point at a real file — a renamed/deleted module left in
    the allowlist is dead config that could later shadow a genuine violation."""
    missing = [rel for rel in _ALLOWED if not (APP_ROOT / rel).is_file()]
    assert not missing, f"Allowlist references non-existent files: {sorted(missing)}"


# --- The detection patterns themselves (a neutered pattern silently disables the guard) ---

_CANONICAL_OFFENDERS = (
    "from llama_index.llms.openai import OpenAI",
    "service = OpenAILLMService(model='gpt-4o')",
    "resp = client.chat.completions.create(model='gpt-4o')",
)


def test_patterns_match_canonical_openai_text_generation():
    """Each forbidden construction must be caught by at least one pattern. If a refactor
    ever loosens these regexes, this fails before the guard goes quietly blind."""
    for snippet in _CANONICAL_OFFENDERS:
        assert any(p.search(snippet) for p in _TEXT_GEN_PATTERNS), (
            f"no allowlist pattern matches a canonical OpenAI text-gen line: {snippet!r}"
        )


def test_patterns_do_not_flag_the_sanctioned_deepseek_default():
    """The default provider (DeepSeek, routed through get_llm) must not trip the OpenAI
    guard — otherwise the allowlist would be fighting the intended default path."""
    benign = (
        "from llama_index.llms.deepseek import DeepSeek",
        "llm = DeepSeek(model='deepseek-chat', api_key=key)",
    )
    for snippet in benign:
        assert not any(p.search(snippet) for p in _TEXT_GEN_PATTERNS), (
            f"a DeepSeek line false-matched an OpenAI guard pattern: {snippet!r}"
        )
