# Testing & Evals Harness — Validation

## Automated
- [x] `make test` green: fixture self-tests, scenario schema validation, adapter units.
      Verified: 38 passed, 1 skipped (the `db_session` fixture, no Postgres reachable
      in this dev sandbox — it skips cleanly rather than failing).
- [x] `make transcript` fixture mode green for deterministic structural assertions.
      Post-merge PDF validation must run with no `requires: [scheduling]` skips; visual
      scenario skips are acceptable only when Tier 3 is not being claimed.
- [x] `make eval` harness plumbing verified with real judge keys: metrics load,
      thresholds load, judge calls execute, and the implemented canaries fail their
      targeted metrics as designed. Historical OpenAI run 2026-07-08: 22/28 in 4m42s;
      default DeepSeek run 2026-07-08: 25/28 in 5m07s.
- [ ] Ordinary scenario eval quality green. Current blocker: 6 non-canary scenarios
      scored below threshold — `core_{dryer,hvac,washer}_safety` and
      `scheduling_{happy_booking,no_tech_in_zip,slot_conflict}`. Because these judge
      hand-authored fixture transcripts, the next work is fixture enrichment or rubric/
      threshold calibration in `evals/`; canary failures do not count as regressions.
- [x] **Canary suite red-as-expected (implemented set)**: every implemented
      deliberate-failure transcript fails its target metric (Knowledge Retention, Role
      Adherence, safety interrupt, booking read-back). A canary going green fails the
      harness gate. The added PDF-grounded canaries for fabricated error-code advice
      and prompt-injection compliance remain pending below.
- [x] Missing active judge key → `make eval` exits with a loud skip warning; `make
      test`/`make transcript` unaffected. Default key is `DEEPSEEK_API_KEY`;
      `OPENAI_API_KEY` applies only with `EVAL_JUDGE_PROVIDER=openai`. Verified skip
      behavior exists; this skip is not a green submission gate.
- [x] `make lint` clean. Verified: `ruff check .` and `ruff format --check .` both pass.
- [ ] **PDF-grounded classes (plan group 7, unimplemented)**: elicitation + robustness
      + faithfulness scenarios green in fixture mode; the two new canaries
      (`fabricated_error_code`, `injection_compliance`) red-as-expected; structural
      faithfulness assertion green on every core scenario (steps traceable to the
      knowledge YAMLs); tool-selection ≥ 0.9 and consistency 3/3 in live mode;
      latency p50/p95 report produced (advisory — no pass/fail until the budget
      decision); vision golden set ≥ 5/6 when Tier 3 is claimed.
- [ ] Fixture-contract expansion green: recorded/live transcripts include `tool_trace`
      with args, `steps_given`, model metadata, and timing fields; schema/adapter tests
      prove backward-compatible handling of old fixtures and strict handling for new
      PDF-grounded scenarios.
- [ ] Tool-selection accuracy green: expected tool names and critical args match
      instrumentation traces at ≥ 0.9, including appliance, symptom key/error code,
      zip, slot id, customer fields, issue summary, and explicit confirmation state.
- [ ] Provider allowlist guard green: automated static test proves no OpenAI
      text-generation calls outside `LLM_PROVIDER=openai` and
      `EVAL_JUDGE_PROVIDER=openai`; OpenAI call sites are limited to vision, STT, TTS,
      and the two explicit escape hatches.
- [ ] Live-agent transcript/eval acceptance: `make eval-live` (or its implementation
      equivalent) runs the structural and judged scenarios against the real agent with
      a migrated/seeded DB. This is the final integration acceptance path and remains
      separate from fixture eval quality.
- [ ] PDF voice readiness acceptance: a real Twilio call transcript passes greeting,
      diagnosis, no-reask memory, safety interrupt, scheduling read-back, STT→agent→TTS
      seam, and first-audio latency reporting.

## Manual
1. Read one scenario YAML end-to-end and confirm the deterministic asserts and the eval
   rubrics express the same intent (no drift between layers). See
   `evals/scenarios/core/oven_safety.yaml` + `evals/fixtures/transcripts/
   core_oven_safety.json` for a clean example; `evals/scenarios/canaries/
   safety_ignored.yaml` for the deliberate-failure counterpart.
2. Inspect a DeepEval failure report for a canary — the metric reason names the actual
   defect (e.g. "zip was asked twice"). Structural layer confirmed (`make transcript`
   prints the exact failure reason, e.g. "field 'customer.zip' was re-asked
   (never-re-ask violation)"); real-key DeepEval canary failures were verified in the
   2026-07-08 run.
3. Read one robustness scenario + the `injection_resistance` rubric end-to-end and
   confirm both express the same intent; inspect the injection transcript — the agent
   must neither reveal instructions nor break persona.
4. Read one live phone transcript end-to-end and confirm the PDF Tier 1/Tier 2 voice
   path is actually represented, not inferred from the web chat channel.

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true: pytest
      scaffolding, transcript runner, DeepEval harness, scenario matrix, canaries,
      CI skip-warn behavior, and real-key judge plumbing are all present.
- [ ] Ordinary scenario eval quality is green for required Tier 1 + Tier 2 scenarios.
- [ ] PDF-grounded LLM class expansion is implemented and green.
- [ ] Live-agent transcript/eval acceptance is green.
- [ ] PDF voice readiness acceptance is green before submission.
- [x] Deferred scope (audio-level evals, load/perf) already recorded in
      `specs/constitution/roadmap.md` → Enhancement backlog; unchanged by this feature.
- [x] Roadmap Phase 1b remains ticked `[x]` for harness implementation; the red
      ordinary scenarios block their owning feature phases, not the existence of the
      harness.
