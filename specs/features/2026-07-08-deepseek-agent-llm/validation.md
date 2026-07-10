# DeepSeek Agent LLM — Validation

## Automated
- [x] `tests/test_llm_factory.py` green: default = function-calling `DeepSeek` on
      `deepseek-chat`; `DEEPSEEK_MODEL` override respected; missing key raises;
      `LLM_PROVIDER=openai` returns the `gpt-4o` fallback. (4 tests, no network.)
- [x] Full `pytest` suite green — existing agent/tool/pipeline tests inject
      `FakeFunctionCallingLLM`, unaffected (192-test suite green post-integration).
- [x] `ruff check` + `ruff format --check` clean.
- [x] `git grep '"gpt-4o"' app/` → only the explicit `LLM_PROVIDER=openai` fallback
      branch (and TTS/vision model ids, which are out of scope).
- [x] Hardened provider allowlist guard: automated static test fails on any OpenAI
      text-generation construction outside `LLM_PROVIDER=openai` and
      `EVAL_JUDGE_PROVIDER=openai`; OpenAI modality clients remain allowed only for
      vision, STT, and TTS. (Landed 2026-07-09: `tests/test_provider_allowlist.py`
      statically scans `app/` and pins the sanctioned sites — `agent/core.py`
      provider switch, `voice/bot.py` voice factory, `vision/client.py` modality,
      `latency_probe.py` diagnostic — with a staleness check on the allowlist itself.)

## Manual
1. [x] **Live turn RUN 2026-07-08 with a real `DEEPSEEK_API_KEY` (headless, through
   the production `run_turn` + `get_llm()`):** caller text "my washer is making a
   loud grinding noise and showing error E3" → DeepSeek invoked **four tools in one
   turn** (`identify_appliance` → `record_symptom` → `get_troubleshooting_steps` ×2),
   case file mutated to `appliance_type: washer` + the grinding-noise symptom, 14
   sentences streamed. **DeepSeek function calling through `AgentWorkflow` proven
   end-to-end. PASS.**
2. [x] Latency vs. Tier 1 budget — first measurement recorded: first sentence 4.07 s,
   full turn 11.79 s (single sample; first sentence lands after the tool-call round
   trips). Over the web first-audio p50 budget (`specs/latency/budgets.md`) as the
   requirements predicted for
   DeepSeek; the spoken tool filler masks part of it on the WS path. Recorded
   mitigation stays `LLM_PROVIDER=openai`.
   **Measurement + fix program owned by `2026-07-08-latency-engineering/`** —
   **CLOSED 2026-07-10 (loop v2 i9, `loop-ledger-v2.md`)**: two consecutive all-PASS
   3-run MEASUREMENTS under the h1 perceived/meaningful budget split (web meaningful
   p50 medians 2020/2119 ms vs 2800 budget); latency gate flipped hard.
3. [x] `LLM_PROVIDER=openai` smoke — RUN 2026-07-08: same live-turn probe on the
   fallback path PASSED (4 tool calls, washer identified; first sentence 6.16 s,
   full turn 7.54 s — vs DeepSeek's 4.07 s / 11.79 s). Now the shipped demo-day
   default per the tech-stack boundary amendment; A/B program continues in
   `2026-07-08-latency-engineering/` P2-2.

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true.
- [x] All automated gates green, including the provider allowlist guard (2026-07-09);
      manual turn 1 completed.
- [x] Constitution docs updated in the same commit (verified by diff).
- [x] Deferred scope (gateways, reasoner) recorded above; no roadmap phase to tick
      (constitution-revising maintenance feature). Latency follow-up (manual #2) and
      fallback smoke (#3) remain open items, tracked here.
