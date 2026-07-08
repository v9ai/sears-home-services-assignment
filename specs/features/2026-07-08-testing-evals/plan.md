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
      (`evals/scenarios/visual/`) — scheduling/visual marked `requires:` and skipped
      until their features merge (verified live: `make transcript` currently shows all 6
      skipping visibly).

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
      fixture skip, since no Postgres is reachable in this dev sandbox); transcript
      matrix all-PASS with visible `requires:` skips; canary suite red-as-expected
      (2 of 4 canaries active today — `role_adherence` and `booking_no_readback` are
      `canary_layer: eval` and only run under `make eval`; `booking_no_readback` is also
      gated on `requires: [scheduling]`). `make eval` verified to skip loudly (exit 0,
      no pytest invocation) with no `OPENAI_API_KEY`, and to correctly reach a live
      OpenAI call (auth error with a fake key) with one set — full plumbing exercised,
      real judge scoring untested (no real key available in this environment).
- [x] Tick roadmap Phase 1b `[x]` in `specs/constitution/roadmap.md`.

## Integration deltas (lead applies at merge)
- Point `make transcript` / `make eval` from fixture mode to the live agent once
  voice-diagnostic-core merges (integration step 3 in COORDINATION §5). Concretely:
  `scripts/transcript_runner.py` and `evals/adapter.py` currently read
  `evals/fixture_loader.py` (recorded JSON); swap that call for a live driver that
  feeds each scenario's `turns[].caller` into the real agent and records its actual
  replies + case file in the same shape, then this harness's assertions/metrics need
  no other change.
- `evals/gating.py` gates `requires: [scheduling]` / `requires: [visual]` on the
  presence of `app/tools/scheduling_tools.py` + `app/db/models_scheduling.py` (resp.
  `app/tools/visual_tools.py` + `app/db/models_visual.py`). Once those land, the 6
  scheduling/visual scenarios and the `canary_booking_no_readback` canary activate
  automatically — no code change needed here, just re-run the gates.
- The Makefile `test`/`lint`/`transcript`/`eval` target bodies were filled in by this
  feature (no other feature owns them per COORDINATION §3's reasoning — they only
  invoke this feature's own scripts/pytest suites). Confirm at integration that
  `deployment-deliverables`' hardened Dockerfile installs dev extras
  (`pip install .[dev]`) wherever these targets are expected to run, since the
  foundation Dockerfile currently only installs the base (non-dev) dependency set.
- `db_session` (tests/conftest.py) skips cleanly without a reachable Postgres; once a
  Compose `db` is actually up in CI/dev, re-run `make test` to confirm the rollback
  behavior against a live database (only exercised as "skip" in this environment).
