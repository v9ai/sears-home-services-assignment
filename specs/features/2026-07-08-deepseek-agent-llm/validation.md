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

## Manual
1. [x] **Live turn RUN 2026-07-08 with a real `DEEPSEEK_API_KEY` (headless, through
   the production `run_turn` + `get_llm()`):** caller text "my washer is making a
   loud grinding noise and showing error E3" → DeepSeek invoked **four tools in one
   turn** (`identify_appliance` → `record_symptom` → `get_troubleshooting_steps` ×2),
   case file mutated to `appliance_type: washer` + the grinding-noise symptom, 14
   sentences streamed. **DeepSeek function calling through `AgentWorkflow` proven
   end-to-end. PASS.**
2. [ ] Latency vs. Tier 1 budget — first measurement recorded: first sentence 4.07 s,
   full turn 11.79 s (single sample; first sentence lands after the tool-call round
   trips). Over the < 2.0 s p50 first-audio budget as the requirements predicted for
   DeepSeek; the spoken tool filler masks part of it on the WS path. Collect the
   ~5-turn sample via the chat page before deciding; recorded mitigation stays
   `LLM_PROVIDER=openai`.
3. [ ] `LLM_PROVIDER=openai` smoke: one turn on the fallback path still works.

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true.
- [x] All automated gates green; manual turn 1 completed.
- [x] Constitution docs updated in the same commit (verified by diff).
- [x] Deferred scope (gateways, reasoner) recorded above; no roadmap phase to tick
      (constitution-revising maintenance feature). Latency follow-up (manual #2) and
      fallback smoke (#3) remain open items, tracked here.
