# Latency Centralization — Plan

## Groups (in execution order)

### 1. Machine source of truth
- `app/latency/__init__.py` + `app/latency/budgets.py`: frozen `StageBudget`/`E2EBudget`
  dataclasses; stage budgets (eos_to_stt 900, stt_to_first_token 1200,
  first_token_to_first_sentence 800, tts_first_byte 500, first_outbound_frame 100,
  submit_to_first_token 1000); e2e (`PHONE_E2E` 2500/4000, `WEB_E2E` 2000/3500);
  perceived (greeting 1500/500 cached, filler 800); VAD tunables (0.5 default /
  0.4 floor); derived `MICRO_BUDGETS_MS` + `ALL_BUDGETS_MS`.

### 2. Code fixes
- `app/voice/metrics.py`: monotonic clock; `_TRACKED_FRAMES` type filter before the
  dedup set; timer reset on `VADUserStartedSpeakingFrame`/`UserStartedSpeakingFrame`.
- `scripts/latency_bench.py`: `_e2e_summary(records, field, budget)`; web→`WEB_E2E`,
  phone→`PHONE_E2E`; `budgets_ms` from module; `schema_version: 2`.
- `app/phone/latency.py`: `P50_BUDGET_S`/`P95_BUDGET_S` aliased from `PHONE_E2E`.
- `app/voice/bot.py`: `_build_vad_analyzer` default from `VAD_STOP_SECS_DEFAULT`;
  below-floor `voice.vad.stop_secs_below_safe_floor` log_event.

### 3. Existing-test pin migration
- `tests/voice/test_voice_latency_e2e.py::test_budgets_unchanged` → pins via module
  (PHONE + WEB).
- `tests/latency/test_channel_guards.py::test_filler_beats_slow_llm` → margin =
  `FILLER_AFTER_EOS_MS / 1000 / 2`.

### 4. Canonical docs
- `specs/latency/budgets.md` (parsable table + envelopes + tunables + gate policy).
- This spec triplet.
- Reference edits: latency-engineering (stage-budgets section → reference; contract
  table names; "versioned here only" claim), telephony-twilio §budget,
  voice-diagnostic-core §budget, deepseek-agent-llm §latency-note,
  pipecat-hardening validation §manual-3, technical-design §latency-budgets
  (summary rows kept, canonical pointer added).

### 5. New tests
- `tests/latency/test_budgets_module.py`, `tests/latency/test_budget_spec_sync.py`,
  `tests/voice/test_greeting_latency.py`, `tests/voice/test_vad_config.py`,
  `tests/test_latency_probe.py`; extensions to `tests/voice/test_voice_metrics.py`,
  `tests/voice/test_voice_latency_e2e.py`, `tests/test_latency_bench.py`,
  `tests/phone/test_latency.py`.

### 6. Verify
- See `validation.md`.
