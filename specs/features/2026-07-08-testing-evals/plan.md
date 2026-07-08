# Testing & Evals Harness — Plan

Implement in dependency order; runs fully in parallel with other features per
`COORDINATION.md` §4 (fixture transcripts, no `app.agent` import).

## 1. pytest scaffolding
- [x] `tests/conftest.py`: async event-loop fixture (via `asyncio_mode = "auto"`), DB
      session fixture (per-test rollback, skips cleanly without a reachable Postgres),
      `FakeLLM`/`FakeAgent`, technician/session factories.
- [x] Harness self-tests: fixtures import and roll back cleanly
      (`tests/test_harness_fixtures.py`).

## 2. Scenario schema + matrix
- [x] `evals/scenarios/schema.py` + loader with validation.
- [x] Author the ~24-scenario matrix: 6 appliances × (happy · safety · error-code) = 18
      (`evals/scenarios/core/`), scheduling ×4 (`evals/scenarios/scheduling/`), visual ×2
      (`evals/scenarios/visual/`). `requires:` gates were used during parallel
      development; post-merge, scheduling scenarios are required for PDF Tier 2, while
      visual scenarios gate only the optional Tier 3 claim.

## 3. Transcript runner
- [x] `scripts/transcript_runner.py`: scripted caller turns → recorded transcript +
      case-file snapshots → deterministic assertions from the scenario file.
- [x] `make transcript` target body; runs against recorded fixture transcripts
      (`evals/fixtures/transcripts/*.json`) until integration, then the live agent.

## 4. DeepEval harness                                 ⏸ review after this group
- [x] `evals/adapter.py`: recorded transcript → `ConversationalTestCase`.
- [x] Metric config (`evals/metrics.py`): Knowledge Retention, Role Adherence,
      Conversation Completeness; G-Eval rubrics (safety-interrupt, booking-confirmation,
      photo-findings).
- [x] `evals/thresholds.py` pinned per requirements; judge `gpt-4o`.
- [x] `make eval` target body + skip-with-warning on missing `OPENAI_API_KEY`
      (belt-and-suspenders: the Makefile itself skips before invoking pytest, and
      `evals/conftest.py` also skip-marks every collected item as a second layer).

## 5. Canaries
- [x] Fixture transcripts that must FAIL each metric (re-asked zip, persona break,
      ignored gas mention, booking without read-back); a canary passing = harness bug.
      `evals/test_canaries.py` asserts the opposite of `test_conversations.py` for each
      one. Structurally-checkable canaries (re-asked zip, ignored gas mention) are also
      asserted red by `scripts/transcript_runner.py`'s canary section.

## 6. Gates
- [x] `make lint` clean; `make test` clean (38 passed, 1 skipped — the `db_session`
      fixture skip, since no Postgres was reachable in that sandbox); transcript matrix
      fixture mode green; canary suite red-as-expected. `make eval` skip behavior was
      verified with no `OPENAI_API_KEY`; later real-key run on 2026-07-08 verified judge
      plumbing and all 4 canaries, but ordinary fixture quality remains red at 22/28.
- [x] Tick roadmap Phase 1b `[x]` in `specs/constitution/roadmap.md`.

## 7. PDF-grounded LLM test classes (added 2026-07-08, unimplemented)
- [ ] Schema extension: `class` field + `expected_tools` + new rubric literals
      (`elicitation`, `greeting_rapport`, `groundedness`, `injection_resistance`) in
      `evals/scenarios/schema.py`.
- [ ] New scenario files + fixtures: vague-opener ×2 in `core/`;
      `evals/scenarios/robustness/` (injection, out-of-domain microwave, off-topic,
      hostile caller); `evals/scenarios/faithfulness/`.
- [ ] New G-Eval rubrics in `evals/metrics.py` (4) + thresholds in
      `evals/thresholds.py` (tool-selection 0.9, vision 5/6, consistency exact).
- [ ] Structural faithfulness assertion in `evals/assertions.py`
      (`steps_given ⊆ knowledge[appliance][symptom_key].steps` via the knowledge
      loader).
- [ ] Tool-trace already emitted by the live driver — add `expected_tools`
      assertions; tool-selection accuracy report.
- [ ] Consistency/latency live harness: drive sampled scenarios 3× at temp 0
      (identical appliance + tool sequence); latency p50/p95 report (advisory).
- [ ] Vision golden set: ≥6 labeled photos in `evals/fixtures/images/` + accuracy
      gate (Tier 3-claim only).
- [ ] 2 new canaries wired into `test_canaries.py`: `canary_fabricated_error_code`
      (groundedness) + `canary_injection_compliance` (injection_resistance).

## Integration deltas (lead applies at merge)
- Point `make transcript` / `make eval` from fixture mode to the live agent once
  voice-diagnostic-core merges (integration step 3 in COORDINATION §5).
  **SHIPPED with this feature** as `evals/live_driver.py` + the runner's `--live`
  flag (`make transcript` stays fixture-mode/offline as the CI default; a live run is
  `python scripts/transcript_runner.py --live`, needing an LLM key + migrated/seeded
  DB). Verified post-merge 2026-07-08: fixture-mode gate green on main; live mode
  remains the final integrated-agent acceptance path (see roadmap → Integration status).
- `evals/gating.py` gates `requires: [scheduling]` / `requires: [visual]` on the
  presence of `app/tools/scheduling_tools.py` + `app/db/models_scheduling.py` (resp.
  `app/tools/visual_tools.py` + `app/db/models_visual.py`). After merge, scheduling
  scenarios must be active for the required PDF path; visual scenarios are active only
  for the optional Tier 3 claim.
- The Makefile `test`/`lint`/`transcript`/`eval` target bodies were filled in by this
  feature (no other feature owns them per COORDINATION §3's reasoning — they only
  invoke this feature's own scripts/pytest suites). Confirm at integration that
  `deployment-deliverables`' hardened Dockerfile installs dev extras
  (`pip install .[dev]`) wherever these targets are expected to run, since the
  foundation Dockerfile currently only installs the base (non-dev) dependency set.
- `db_session` (tests/conftest.py) skips cleanly without a reachable Postgres; once a
  Compose `db` is actually up in CI/dev, re-run `make test` to confirm the rollback
  behavior against a live database (only exercised as "skip" in this environment).
