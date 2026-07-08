# Testing & Evals Harness — Validation

## Automated
- [x] `make test` green: fixture self-tests, scenario schema validation, adapter units.
      Verified: 38 passed, 1 skipped (the `db_session` fixture, no Postgres reachable
      in this dev sandbox — it skips cleanly rather than failing).
- [x] `make transcript` fixture mode green for deterministic structural assertions.
      Post-merge PDF validation must run with no `requires: [scheduling]` skips; visual
      scenario skips are acceptable only when Tier 3 is not being claimed.
- [x] `make eval` harness plumbing verified with a real `OPENAI_API_KEY`: metrics load,
      thresholds load, judge calls execute, and all 4 canaries fail their targeted
      metrics as designed. Real-key run 2026-07-08: 22/28 passed in 4m42s.
- [ ] Ordinary scenario eval quality green. Current blocker: 6 non-canary scenarios
      scored below threshold — `core_{dryer,hvac,washer}_safety` and
      `scheduling_{happy_booking,no_tech_in_zip,slot_conflict}`. Because these judge
      hand-authored fixture transcripts, the next work is fixture enrichment or rubric/
      threshold calibration in `evals/`; canary failures do not count as regressions.
- [x] **Canary suite red-as-expected**: every deliberate-failure transcript fails its
      target metric (Knowledge Retention, Role Adherence, safety interrupt, booking
      read-back). A canary going green fails the harness gate.
- [x] Missing `OPENAI_API_KEY` → `make eval` exits with a loud skip warning; `make
      test`/`make transcript` unaffected. Verified: `make eval` prints a WARNING and
      exits 0 without running pytest; `evals/conftest.py` is a second skip layer (marks
      every collected item "skipped" with the same reason) for direct `pytest evals`.
      This skip is not a green submission gate.
- [x] `make lint` clean. Verified: `ruff check .` and `ruff format --check .` both pass.
- [ ] **PDF-grounded classes (plan group 7, unimplemented)**: elicitation + robustness
      + faithfulness scenarios green in fixture mode; the two new canaries
      (`fabricated_error_code`, `injection_compliance`) red-as-expected; structural
      faithfulness assertion green on every core scenario (steps traceable to the
      knowledge YAMLs); tool-selection ≥ 0.9 and consistency 3/3 in live mode;
      latency p50/p95 report produced (advisory — no pass/fail until the budget
      decision); vision golden set ≥ 5/6 when Tier 3 is claimed.
- [ ] Live-agent transcript/eval acceptance: run the structural and judged scenarios
      against the real agent with a migrated/seeded DB. This is the final integration
      acceptance path and remains separate from fixture eval quality.

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

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true: pytest
      scaffolding, transcript runner, DeepEval harness, scenario matrix, canaries,
      CI skip-warn behavior, and real-key judge plumbing are all present.
- [ ] Ordinary scenario eval quality is green for required Tier 1 + Tier 2 scenarios.
- [ ] Live-agent transcript/eval acceptance is green.
- [x] Deferred scope (audio-level evals, load/perf) already recorded in
      `specs/constitution/roadmap.md` → Enhancement backlog; unchanged by this feature.
- [x] Roadmap Phase 1b remains ticked `[x]` for harness implementation; the red
      ordinary scenarios block their owning feature phases, not the existence of the
      harness.
