# Voice LLM provider truth (constitution carve-out) — Plan

Implement in dependency order. Run the relevant gate after each group; pause for review
between groups.

## 1. Source of truth                                  [content / data change]
- [x] `specs/constitution/tech-stack.md` — Model-provider boundary: add the dated
      (2026-07-09) realtime-voice carve-out paragraph; scope the "unsetting
      `LLM_PROVIDER` returns to DeepSeek" sentence to the web agent.
- [x] Same file — Models table: split the TTS row into web / phone truth (Cartesia
      `sonic-3.5` phone default), annotate the LLM row with the phone-channel default
      (`VOICE_LLM_MODEL`, `gpt-4o`), extend the STT row with the
      `STT_PROVIDER=cartesia` option.
- [x] Same file — Forbidden patterns: reword the provider-allowlist bullet to name the
      carve-out.
- [x] Same file — Secrets classification: add `DEEPGRAM_API_KEY` / `CARTESIA_API_KEY`
      (backend secrets) and the voice provider/model/voice vars (backend non-secret
      config).

## 3. Pipeline / logic change                          [if pipeline change]
- [x] `git add tests/voice/test_llm_factory.py` — no code change; the untracked test
      file that encodes the carve-out lands with this spec.

## 5. Gates
- [x] `make lint` + `make test` clean (includes `tests/voice/test_llm_factory.py`).
- [x] Grep audit: no doc outside historical/spec-archive context claims
      `gpt-4o-mini-tts` as the *phone* TTS default or DeepSeek as the *phone* LLM
      default.

## 6. Deploy                                           [if deploy in scope]
- [x] No deploy. Record this feature in `specs/constitution/roadmap.md` (Phase 10) and
      tick `[x]` when the DoD holds.
