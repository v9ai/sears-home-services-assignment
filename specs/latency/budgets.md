# Latency Budgets — canonical

The ONLY place latency budget numbers live in prose. Machine source of truth:
`app/latency/budgets.py`. `tests/latency/test_budget_spec_sync.py` regex-parses the
table below and fails if it and the module disagree — in either direction. Every other
spec/doc REFERENCES this file; none restates numbers.

**To change a budget**: edit `app/latency/budgets.py` AND the table below together in
one commit (the sync test enforces the pairing), then re-run `make latency` and record
the decision in the owning feature spec
(`specs/features/2026-07-08-latency-engineering/`).

<!-- budgets:begin -->
| key | budget |
|---|---|
| eos_to_stt_ms | 900 |
| stt_to_first_token_ms | 1200 |
| first_token_to_first_sentence_ms | 800 |
| tts_first_byte_ms | 500 |
| first_outbound_frame_ms | 100 |
| submit_to_first_token_ms | 1000 |
| phone_e2e_p50_ms | 2500 |
| phone_e2e_p95_ms | 4000 |
| web_e2e_p50_ms | 2000 |
| web_e2e_p95_ms | 3500 |
| phone_meaningful_p50_ms | 3200 |
| phone_meaningful_p95_ms | 5100 |
| web_meaningful_p50_ms | 2800 |
| web_meaningful_p95_ms | 4900 |
| answer_to_greeting_ms | 1500 |
| answer_to_greeting_cached_ms | 500 |
| filler_after_eos_ms | 800 |
<!-- budgets:end -->

All values are milliseconds. Stage keys are the canonical trace/report field names
(`app/agent/trace.py` `TurnTrace.to_record()`, `scripts/latency_bench.py` report).

## Envelopes

**h1 budget split (user decision 2026-07-10 — loop-ledger-v2.md §Human decisions #1,
evidence: measurement `20260710T014427Z`):** "first audio" is split into what the
caller HEARS first (the cached greeting/filler — measured 0.2–0.4 ms warm) and the
agent's actual reply. The `*_e2e_*` budgets keep their numbers but are re-scoped as
**first-PERCEIVED-audio** hard tripwires (they only fail if the cache/filler path
breaks); the reply gets its own **meaningful-reply** budgets at the measured floor +
margin (legacy floors at decision time: web 2565 / phone 2585 median p50).

- **Phone perceived** (`phone_e2e_*`): end-of-speech → first PERCEIVED audio (filler
  counts), p50 ≤ 2.5 s / p95 ≤ 4 s. Measured live by `VoiceMetricsObserver`
  (`app/voice/metrics.py`) feeding `LatencyRecorder` (`app/phone/latency.py`).
- **Phone meaningful** (`phone_meaningful_*`): end-of-speech → first audio of the
  agent's reply, p50 ≤ 3.2 s / p95 ≤ 5.1 s. The bench's
  `eos_to_first_audio_ms`/`pipecat_eos_to_first_audio_ms` rows gate here.
- **Web perceived** (`web_e2e_*`): submit → first PERCEIVED audio, p50 ≤ 2.0 s /
  p95 ≤ 3.5 s.
- **Web meaningful** (`web_meaningful_*`): submit → first reply audio, p50 ≤ 2.8 s /
  p95 ≤ 4.9 s. First token ≤ 1.0 s (`submit_to_first_token_ms`).
- **Perceived constants** (assignment §6): call answer → greeting ≤ 1.5 s (≤ 0.5 s
  from the TTS cache); filler audible ≤ 800 ms after end-of-speech.

Stage decomposition (unchanged): VAD stop-hangover, then STT (≤ 900 ms), LLM first
token (≤ 1200 ms), first sentence (≤ 800 ms after first token), TTS first byte
(≤ 500 ms), first outbound frame (≤ 100 ms).

## Latency-critical tunables (knobs, not budgets — recorded in the module)

- `VAD_STOP_SECS` — Silero VAD stop-hangover; default **0.5 s**
  (`VAD_STOP_SECS_DEFAULT`), safe floor **0.4 s** (`VAD_STOP_SECS_MIN_SAFE`). Below the
  floor callers get cut off mid-utterance; an override under it is honored but logs
  `voice.vad.stop_secs_below_safe_floor` (`app/voice/bot.py::_build_vad_analyzer`).

## Gate policy

Advisory→hard per latency-engineering Decision 3: `make latency` always reports
PASS/FAIL per stage; the exit code reflects it only when `LATENCY_GATE_HARD=1`. The
flip to hard is earned by two consecutive all-PASS runs at p50 (see
`specs/features/2026-07-08-latency-engineering/validation.md`).

## Consumers

| Consumer | What it takes |
|---|---|
| `app/phone/latency.py` | `PHONE_E2E` (aliased `P50_BUDGET_S`/`P95_BUDGET_S`) |
| `scripts/latency_bench.py` | `MICRO_BUDGETS_MS`, `PHONE_E2E`, `WEB_E2E` |
| `app/voice/bot.py` | `VAD_STOP_SECS_DEFAULT`, `VAD_STOP_SECS_MIN_SAFE` |
| `tests/latency/`, `tests/voice/`, `tests/phone/` | pins + margins from the module |
