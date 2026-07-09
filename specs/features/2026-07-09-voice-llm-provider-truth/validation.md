# Voice LLM provider truth (constitution carve-out) — Validation

## Automated (only the gates this feature's surface triggers)
- [x] `make lint` + `make test` clean (the landed `tests/voice/test_llm_factory.py`
      asserts: phone LLM default OpenAI `gpt-4o`; `VOICE_LLM_MODEL` decoupled from
      `OPENAI_LLM_MODEL`; `LLM_PROVIDER=deepseek` parity path; `deepseek-reasoner`
      fail-fast; missing-key fail-fast; full toolset registered).                [code changed]

## Manual
1. Read `specs/constitution/tech-stack.md` next to `app/voice/bot.py`
   `_build_llm`/`_build_tts`/`_build_stt` and `app/agent/core.py:get_llm()` — every
   default and env swap named in the constitution matches the code.
2. Grep audit:
   `grep -rn "gpt-4o-mini-tts\|deepseek-chat" README.md docs/technical-design.md specs/constitution/`
   — no line claims a stale phone default; carve-out paragraph present and dated.

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true.
- [x] All automated gates above are green.
- [x] Constitution-revising: `tech-stack.md` updated alongside the change (this IS the
      change); `mission.md` untouched.
- [x] Deferred scope (provider-allowlist test honoring the carve-out) recorded in
      `specs/constitution/roadmap.md` / testing-evals group 7.
- [x] Matching roadmap phase (Phase 10) ticked `[x]`.
