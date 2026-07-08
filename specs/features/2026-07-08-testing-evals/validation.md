# Testing & Evals Harness — Validation

## Automated
- [x] `make test` green: fixture self-tests, scenario schema validation, adapter units.
      Verified: 38 passed, 1 skipped (the `db_session` fixture, no Postgres reachable
      in this dev sandbox — it skips cleanly rather than failing).
- [x] `make transcript` runs the full scenario matrix in fixture mode; deterministic
      assertions pass; `requires:`-gated scenarios skip visibly. Verified: all 18 core
      scenarios PASS; 6 scheduling/visual scenarios SKIP with `requires unmet:
      scheduling`/`visual` printed per scenario.
- [ ] `make eval` in fixture mode: all metrics compute, thresholds load, judge calls
      succeed. **Real-key run 2026-07-08 (lead): 22/28 passed in 4m42s — plumbing
      fully verified, gate honestly RED.** All 4 canaries failed their targeted
      metrics as designed (including the eval-layer role-adherence and
      booking-no-readback ones, now judge-verified). 6 scenarios scored below
      threshold: `core_{dryer,hvac,washer}_safety` (G-Eval safety rubric) and
      `scheduling_{happy_booking,no_tech_in_zip,slot_conflict}`. Since these judge the
      hand-authored fixture transcripts, follow-up is fixture enrichment or rubric/
      threshold calibration in `evals/` — tracked as the open item on this gate.
- [x] **Canary suite red**: every deliberate-failure transcript fails its metric
      (Knowledge Retention canary, Role Adherence canary, safety-rubric canary,
      booking-rubric canary). A green canary fails the gate. Structural layer verified
      live (`make transcript`): the Knowledge Retention and safety-rubric canaries fail
      their structural checks as designed. The Role Adherence and booking-rubric
      canaries are `canary_layer: eval` (persona/read-back defects aren't structurally
      checkable) and are wired into `evals/test_canaries.py`, which asserts
      `metric.is_successful()` is `False` for each — but, per the line above, this is
      unverified against a real judge model. `canary_booking_no_readback` additionally
      requires `scheduling` to be merged before it runs at all (currently skips).
- [x] Missing `OPENAI_API_KEY` → `make eval` exits with a loud skip warning; `make
      test`/`make transcript` unaffected. Verified: `make eval` prints a WARNING and
      exits 0 without running pytest; `evals/conftest.py` is a second skip layer (marks
      every collected item "skipped" with the same reason) for anyone invoking `pytest
      evals` directly, bypassing the Makefile.
- [x] `make lint` clean. Verified: `ruff check .` and `ruff format --check .` both pass.

## Manual
1. Read one scenario YAML end-to-end and confirm the deterministic asserts and the eval
   rubrics express the same intent (no drift between layers). See
   `evals/scenarios/core/oven_safety.yaml` + `evals/fixtures/transcripts/
   core_oven_safety.json` for a clean example; `evals/scenarios/canaries/
   safety_ignored.yaml` for the deliberate-failure counterpart.
2. Inspect a DeepEval failure report for a canary — the metric reason names the actual
   defect (e.g. "zip was asked twice"). Structural layer confirmed (`make transcript`
   prints the exact failure reason, e.g. "field 'customer.zip' was re-asked
   (never-re-ask violation)"); the DeepEval-judge failure reason text is unverified
   pending a real `OPENAI_API_KEY` (see Automated notes above).

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true (pytest
      scaffolding, transcript runner, DeepEval harness, ~24-scenario matrix, canaries,
      CI skip-warn behavior — all present and exercised above).
- [ ] All automated gates above are green (canaries red-as-expected) — green modulo the
      one caveat above (real judge-call scoring untested for lack of an API key in this
      environment); everything short of that is verified.
- [x] Deferred scope (audio-level evals, load/perf) already recorded in
      `specs/constitution/roadmap.md` → Enhancement backlog; unchanged by this feature.
- [x] Roadmap Phase 1b ticked `[x]`.
