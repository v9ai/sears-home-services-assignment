# Latency Engineering — Validation

> **Phone path re-homed to Pipecat (2026-07-09).** The automated `tests/latency/` guards
> and the measured-acceptance numbers below were captured on the pre-Pipecat shared/phone
> path; on the **phone** channel the equivalent guarantees (streaming TTS, no inline
> serialization, per-call metrics) are now Pipecat internals verified in `tests/voice/` and
> by Pipecat's own metrics — see `specs/features/2026-07-09-pipecat-voice-port/`. The
> `tests/latency/` suite continues to protect the **web** channel. The **e2e envelope
> p50 ≤ 2.5 s / p95 ≤ 4 s** is the acceptance target for both channels.

## Automated
- [ ] Harness self-tests: report schema, budget-table math, skip-loud without keys.
- [ ] TTS-cache hit test: greeting/filler playback performs ZERO TTS API calls
      (spy on `tts.synthesize`); cache filename = text hash (stale-cache guard).
- [ ] Async-IO test: persist/recording still land (eventually) and a write failure
      never surfaces into the turn; transcript ordering preserved.
- [ ] First-clause chunker unit: first emission at clause boundary, subsequent at
      sentence boundaries; no text lost.
- [ ] Existing full suite green unchanged after every fix group (behavioral
      equivalence — requirements Decision 2).

- [ ] **Regression suite (`tests/latency/`) green** — parallelism, backpressure,
      cache-hit, filler-timing, async-IO, first-clause, pipeline-overhead floor; each
      fix's guard landed with the fix. The overhead-floor test alone must catch any
      reintroduced serialization/inline-await/sync-IO (verified by a deliberate
      revert-canary during implementation: un-parallelize TTS locally → the suite
      MUST go red before re-landing the fix).
- [ ] Live tripwires active in `make latency`: serialization ratio ≤ 0.7 on
      multi-sentence turns · prose-before-tools ≥ 4/5.

## Measured acceptance
- [x] **Baseline recorded (2026-07-08, pre-optimization)**: LLM TTFT 801 ms · TTS
      first-byte 573 ms / sentence 1324 ms · STT 588 ms · dev↔OpenAI TTFB 0.93 s ·
      instrumented turn: first sentence 3.43 s, first audio 4.68 s, turn total
      15.04 s with 11.34 s serialized TTS (7 sentences) · hosted greeting 1.21 s.
      (Probe scripts in scratchpad; numbers pinned here and in requirements § RCA.)
- [ ] Per-group reruns showing the expected deltas (P0-1/2: greeting/filler budgets
      pass; **P0-3: turn wall ≈ max(LLM, TTS tail), not ΣTTS — target ≤ ~6 s for the
      baseline 7-sentence turn**; P1: first-sentence budget).
- [ ] **Two consecutive all-PASS runs**: every stage budget at p50, e2e
      eos→first-audio p50 ≤ 2.5 s / p95 ≤ 4 s → flip the gate to hard.
- [ ] Provider A/B table recorded with the pinned demo-day decision (P2-2).

- [ ] Round-3 negative findings honored: no latency claims attached to P1-2/O13
      (cost-only); TTS instructions retained; memory-window work NOT undertaken
      (measured negligible).
- [ ] Deep-RCA fixes verified: O8 median sentences/turn ≤ 3 on live sample with
      Completeness stable · O9/O12 web first-audio and inter-sentence gap improve by
      the measured deltas (≈ 270 ms/sentence + decode gaps) · O10 hosted probe column
      added to the RCA table (container→OpenAI RTT) · O11 no cold start observed
      across a 2 h idle test window.

## Manual
1. One live phone call (now the Pipecat pipeline, `app/voice/`): greeting effectively
   instant on answer (constant `TTSSpeakFrame(GREETING)` queued on connect, no LLM round
   trip); streaming reply begins promptly with native barge-in (interrupt mid-reply and it
   stops); no dead-air stretch > 2.5 s in normal turns. Read the eos→first-audio envelope
   from Pipecat's per-call metrics (`enable_metrics=True`) rather than the retired phone
   `turn_trace`.
2. Web chat: same subjective envelope on submit.
3. Read the latest report table against the runbook — every FAIL row maps to a fix
   menu entry (no orphan failures).

## Definition of done
- [ ] Scope A (harness), B (runbook usable end-to-end), C (P0+P1 landed; P2 decided
      and recorded) all observably true.
- [ ] Latency gate flipped to hard; testing-evals Decision 6 + deepseek-agent-llm
      validation #2 updated with the measured evidence.
- [ ] Deferred scope (Realtime API revisit clause, streaming STT, self-hosting)
      recorded above.
- [ ] Roadmap Phase 8 ticked `[x]` only on the two consecutive all-PASS runs.
