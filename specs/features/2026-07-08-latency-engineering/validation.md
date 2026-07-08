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

## Measured acceptance
- [ ] Baseline report archived (`data/latency/`), then per-group reruns showing the
      expected deltas (P0: greeting/filler budgets pass; P1: first-sentence budget).
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
