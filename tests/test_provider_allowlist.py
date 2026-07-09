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
