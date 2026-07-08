# DeepSeek Agent LLM — Validation

## Automated
- [ ] `tests/test_llm_factory.py` green: default = function-calling `DeepSeek` on
      `deepseek-chat`; `DEEPSEEK_MODEL` override respected; missing key raises;
      `LLM_PROVIDER=openai` returns the `gpt-4o` fallback.
- [ ] Full `pytest` suite green — existing agent/tool/pipeline tests inject
      `FakeFunctionCallingLLM` and must be unaffected.
- [ ] `ruff check` + `ruff format --check` clean.
- [ ] `git grep '"gpt-4o"' app/` → only the explicit `LLM_PROVIDER=openai` fallback
      branch (and TTS/vision model ids, which are out of scope).

## Manual
1. With a real `DEEPSEEK_API_KEY` in `.env`: run the app, open the chat page, send
   "my washer is making a grinding noise and shows error E3" — the reply must show a
   tool call landed (case-file panel gains `appliance_type: washer` + the symptom),
   proving DeepSeek function calling end-to-end through `AgentWorkflow`.
2. Check `first_token_latency_ms` / `first_audio_latency_ms` logs over ~5 turns against
   the Tier 1 budget (first audio < 2.0 s p50 / 3.5 s p95); if consistently over,
   record it and evaluate the `LLM_PROVIDER=openai` mitigation.
3. `LLM_PROVIDER=openai` smoke: one turn on the fallback path still works.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates green; manual turn 1 completed.
- [ ] Constitution docs updated in the same commit (verified by diff).
- [ ] Deferred scope (gateways, reasoner) recorded above; no roadmap phase to tick
      (constitution-revising maintenance feature).
