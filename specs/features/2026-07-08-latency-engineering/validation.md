# Latency Engineering — Validation

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

## Manual
1. One live phone call: greeting effectively instant on answer; filler within ~1 s of
   finishing speaking; no dead-air stretch > 2.5 s in normal turns.
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
