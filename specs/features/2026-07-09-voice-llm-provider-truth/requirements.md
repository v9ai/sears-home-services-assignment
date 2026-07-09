# Voice LLM provider truth (constitution carve-out) — Requirements

## Source
Pasted requirement (not from the roadmap):
> Gap analysis vs the assignment PDF (2026-07-09): the phone pipeline's LLM code default
> is OpenAI `gpt-4o` (`app/voice/bot.py:_build_llm`) while `tech-stack.md`'s
> Model-provider boundary says every text-LLM call runs on DeepSeek and "unsetting
> `LLM_PROVIDER` returns to DeepSeek". User decision: keep `gpt-4o` on the phone path
> and revise the constitution with an explicit realtime-voice carve-out — a documented,
> honest tradeoff — rather than switching the phone default to DeepSeek.

## Scope

### Included
- `specs/constitution/tech-stack.md` tells the truth about every shipped provider
  default:
  - **Model-provider boundary**: a dated realtime-voice carve-out paragraph — the
    Pipecat phone pipeline's LLM defaults to OpenAI (`VOICE_LLM_MODEL`, default
    `gpt-4o`) even when `LLM_PROVIDER` is unset; `LLM_PROVIDER=deepseek` opts the phone
    loop back into `deepseek-chat`. The "unsetting `LLM_PROVIDER` returns to DeepSeek"
    sentence is scoped to the web agent.
  - **Models table**: TTS row split web (`gpt-4o-mini-tts`) / phone (**Cartesia
    `sonic-3.5`** default, `TTS_PROVIDER=openai|deepgram` swaps); LLM row notes the
    phone-channel default; STT row mentions the `STT_PROVIDER=cartesia` (`ink-whisper`)
    option.
  - **Forbidden patterns**: the provider-allowlist bullet names the phone-pipeline
    carve-out as a sanctioned path alongside the two env-gated escape hatches.
  - **Secrets classification**: `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY` → backend
    secrets; `STT_PROVIDER`, `TTS_PROVIDER`, `VOICE_LLM_MODEL`, `CARTESIA_VOICE_ID`,
    `CARTESIA_TTS_MODEL`, `CARTESIA_STT_MODEL`, `DEEPGRAM_AURA_VOICE`,
    `OPENAI_TTS_VOICE` → backend non-secret config.
- `tests/voice/test_llm_factory.py` (already written, untracked) lands with this spec —
  it encodes the carve-out: phone default = OpenAI `gpt-4o`, `VOICE_LLM_MODEL`
  decoupled from `OPENAI_LLM_MODEL`, `LLM_PROVIDER=deepseek` parity path,
  `deepseek-reasoner` fail-fast, missing-key fail-fast, full toolset registration.

### Not included (deferred)
- No behavior change to `app/voice/bot.py` or `app/agent/core.py` — the code already
  does what this spec documents; this feature makes the constitution match the code.
- README / `docs/technical-design.md` provider rows — already reconciled to the
  `29f3552` defaults (pipecat-hardening validation item 2, verified 2026-07-09).
- The provider-allowlist automated test (testing-evals plan group 7) — its rule text
  must honor this carve-out when implemented; noted there, built there.

### Contract shapes
- Source-of-truth file(s): `specs/constitution/tech-stack.md` (Models · Model-provider
  boundary · Forbidden patterns · Secrets classification).
- Code truth mirrored: `app/voice/bot.py` `_build_llm`/`_build_tts`/`_build_stt`;
  `app/agent/core.py:get_llm()`.
- Pipeline / build target: `make lint` · `make test`.

## Decisions
1. **Keep OpenAI `gpt-4o` as the phone-pipeline LLM default (carve-out), don't switch
   to DeepSeek** — user decision 2026-07-09. Rationale: measured latency
   (latency-engineering P2-2: DeepSeek 4.07 s first sentence vs the phone
   end-of-speech→first-audio budget) and reliable *streamed* function calling inside
   Pipecat's realtime loop. DeepSeek remains the default for the web agent and every
   non-realtime text-LLM call; the boundary section stays binding for those.
2. **Constitution documents code, not aspiration** — every Models-table row and secrets
   row must name the shipped default and the env swap, so a reviewer reading
   `tech-stack.md` and a reviewer reading `bot.py` see the same system.
3. **Deploy path**: no deploy — constitution + one already-passing test file.
4. **Gate path**: `make lint` + `make test` (includes `tests/voice/test_llm_factory.py`);
   manual grep audit that no doc claims a stale default.

## Architecture impact
- Component / plane touched: constitution docs only (`specs/constitution/tech-stack.md`).
- **Constitution-revising**: the Model-provider boundary (BINDING, 2026-07-08) gains a
  realtime-voice carve-out; the Forbidden-patterns allowlist bullet is reworded; the
  Models table and Secrets classification are corrected. `mission.md` unchanged (no
  non-negotiable touched).
- Precedent followed: `2026-07-08-deepseek-agent-llm` (constitution-revising, updated
  `tech-stack.md` alongside the change in the same commit).

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; real files:
  `app/voice/bot.py`, `app/agent/core.py`, `tests/voice/test_llm_factory.py`,
  `.env.example` (already lists `STT_PROVIDER=deepgram` / `TTS_PROVIDER=cartesia` /
  `LLM_PROVIDER=openai` — no edit needed).
- Constraints: the boundary's escape hatches (`LLM_PROVIDER`, `EVAL_JUDGE_PROVIDER`)
  and the DeepSeek eval judge stay as-is; no new abstraction; no provider SDK added.
- Open questions / explicit deferrals: none.
