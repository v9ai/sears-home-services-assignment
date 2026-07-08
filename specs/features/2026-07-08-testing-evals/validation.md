# Testing & Evals Harness — Validation

## Automated
- [ ] `make test` green: fixture self-tests, scenario schema validation, adapter units.
- [ ] `make transcript` runs the full scenario matrix in fixture mode; deterministic
      assertions pass; `requires:`-gated scenarios skip visibly.
- [ ] `make eval` in fixture mode: all metrics compute, thresholds load, judge calls
      succeed.
- [ ] **Canary suite red**: every deliberate-failure transcript fails its metric
      (Knowledge Retention canary, Role Adherence canary, safety-rubric canary,
      booking-rubric canary). A green canary fails the gate.
- [ ] Missing `OPENAI_API_KEY` → `make eval` exits with a loud skip warning, nonzero
      "skipped" status visible in CI output; `make test`/`make transcript` unaffected.
- [ ] `make lint` clean.

## Manual
1. Read one scenario YAML end-to-end and confirm the deterministic asserts and the eval
   rubrics express the same intent (no drift between layers).
2. Inspect a DeepEval failure report for a canary — the metric reason names the actual
   defect (e.g. "zip was asked twice").

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green (canaries red-as-expected).
- [ ] Deferred scope (audio-level evals, load/perf) recorded in the roadmap backlog.
- [ ] Roadmap Phase 1b ticked `[x]`.
