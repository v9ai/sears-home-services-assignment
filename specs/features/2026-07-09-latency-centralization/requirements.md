# Latency Centralization (one source of truth + extensive tests + fixes) — Requirements

## Source
User directive (2026-07-09):
> create or centralize specs related to latency and add tests related to this very
> extensively and apply fixes

## Problem

Latency budgets were restated across **8 prose locations** (latency-engineering,
telephony-twilio, voice-diagnostic-core, deepseek-agent-llm, pipecat-hardening,
docs/technical-design.md, constitution) and **hard-coded in 4 code locations**
(`app/phone/latency.py`, `scripts/latency_bench.py`, the
`test_budgets_unchanged` pin, comments in `app/voice/bot.py`) — with verified
divergence and verified instrumentation bugs:

1. **Bench gated web against the phone budget** — `scripts/latency_bench.py`
   `_e2e_summary` applied 2500/4000 ms to BOTH channels; voice-diagnostic-core and
   technical-design define web as 2000/3500 ms. A web regression to 2.4 s p50 would
   have passed.
2. **`app/voice/metrics.py` used `time.time()`** (wall clock; NTP steps → negative or
   garbage samples) instead of `time.monotonic()`.
3. **`_seen_frame_ids` grew unboundedly** — every frame id (including the ~50/s audio
   flood) was added to the dedup set before the type check, for the call's lifetime.
4. **Stale end-of-speech timer** — a turn that never reached TTS (safety-gated,
   aborted) or a caller resuming speech mid-pause left the old timestamp armed; the
   next turn's sample measured from the WRONG end-of-speech (inflated). Nothing reset
   the timer on `UserStartedSpeakingFrame`/`VADUserStartedSpeakingFrame`.
5. **Spec contract drift** — the latency-engineering "Regression-proof test contract"
   table named 4 tests that don't exist under those names (they were implemented under
   different names in `tests/latency/`).

## Scope

### A. Centralize
- NEW `app/latency/budgets.py` — machine source of truth: frozen `StageBudget` /
  `E2EBudget` dataclasses, all stage/e2e/perceived budgets, VAD tunables, and the
  derived `MICRO_BUDGETS_MS` / `ALL_BUDGETS_MS` views. Leaf module (zero `app.*`
  imports — importable from `scripts/` and anywhere in `app/` with no cycle risk).
- NEW `specs/latency/budgets.md` — canonical prose: ONE machine-parsable table between
  `<!-- budgets:begin/end -->` markers plus envelope/tunable/gate-policy prose.
- All code consumers import from the module; all specs/docs reference the canonical
  doc instead of restating numbers.

### B. Test (extensive; all hermetic, in `make test`)
- `tests/latency/test_budgets_module.py` — value pins, immutability, derived-view
  consistency, web-stricter-than-phone.
- `tests/latency/test_budget_spec_sync.py` — the anti-drift centerpiece: markdown
  table ↔ module dict-equality (both directions), bench/phone-module identity checks,
  technical-design summary rows, contract-table test names must exist.
- `tests/voice/test_voice_metrics.py` extensions — monotonic clock, per-turn timer
  isolation, speech-resume reset, abandoned-turn no-leak, bounded dedup set,
  over-budget logging.
- `tests/voice/test_voice_latency_e2e.py` extensions — multi-turn aggregation, mixed
  over/under-budget percentiles, Pipecat overhead floor, stage-dominant attribution.
- `tests/voice/test_greeting_latency.py` — greeting speaks without an LLM round trip
  (the structural guarantee behind answer→greeting ≤ 1.5 s).
- `tests/voice/test_vad_config.py` — default/override/below-floor-logging for
  `VAD_STOP_SECS`.
- `tests/test_latency_probe.py` — `/debug/latency-probe` sections, error containment,
  not-mounted-by-default.
- `tests/test_latency_bench.py` + `tests/phone/test_latency.py` extensions — web
  budget gating, report schema v2, percentile edge cases, boundary-inclusive budgets.

### C. Fix
1. `time.time()` → `time.monotonic()` in `VoiceMetricsObserver`.
2. Reset the end-of-speech timer on user-started-speaking frames (measurement is now
   "LAST end-of-speech → first TTS"; kills the stale-timer leak).
3. Type-filter frames BEFORE the dedup set (bounded memory; audio flood excluded).
4. Bench: web gated by `WEB_E2E`, phone by `PHONE_E2E`; per-summary budget fields;
   `budgets_ms` sourced from the module; report `schema_version: 2`.
5. `app/phone/latency.py` budgets from the module (back-compat aliases kept).
6. `app/voice/bot.py` VAD default from the module + below-floor `log_event`
   (`voice.vad.stop_secs_below_safe_floor`) — log, never clamp.
7. Contract-table names corrected to the actual test names; stale "budgets versioned
   in this spec only" claim amended.

## Decisions
1. **Module = machine SoT; `specs/latency/budgets.md` = prose SoT** — hand-maintained
   table verified by a sync test, not a generation step (no build tooling exists here;
   a failing test is an equally strong guarantee with less machinery).
2. **Historical *measured* numbers stay** where they are — they are measurements, not
   budgets. Only *normative* budget statements are replaced with references.
3. **Tests keep their names; the spec table updates** — renaming tests churns history
   for zero safety gain. `test_spec_contract_table_names_exist` prevents recurrence.
4. **Web and phone keep separate budgets** (web stricter: no L1–L3 stages), now gated
   separately in the bench — the divergence was the bug, not the two numbers.
5. **VAD floor logs, never clamps** — an operator override stays an override; the
   floor is observability.

## Deliberately not fixed (recorded)
- `percentile()` nearest-rank method — adequate at N=5–50 sample sizes; now
  edge-case-tested instead of replaced.
- `app/agent/trace.py` — already monotonic with idempotent marks; verified clean.
- OpenAI Realtime API stance unchanged (forbidden unless budgets fail — constitution).

## Architecture impact
Invariant-preserving. New leaf package `app/latency/`; no behavior change on the
happy path other than corrected measurements and corrected web gating. Report schema
bumped to v2 (`budgets_ms` keys renamed to per-channel, `budget_p50/p95_ms` added to
e2e summaries) — `data/latency/*.json` consumers compare across runs by table, and no
code reads old reports.
