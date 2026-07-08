# Testing & Evals Harness — Plan

Implement in dependency order; runs fully in parallel with other features per
`COORDINATION.md` §4 (fixture transcripts, no `app.agent` import).

## 1. pytest scaffolding
- [ ] `tests/conftest.py`: async event-loop fixture, DB session fixture (Compose `db`,
      per-test rollback), `FakeLLM`/`FakeAgent`, technician/session factories.
- [ ] Harness self-tests: fixtures import and roll back cleanly.

## 2. Scenario schema + matrix
- [ ] `evals/scenarios/schema.py` + loader with validation.
- [ ] Author the ~24-scenario matrix: 6 appliances × (happy · safety · error-code),
      scheduling ×4, visual ×2 — scheduling/visual marked `requires:` and skipped until
      their features merge.

## 3. Transcript runner
- [ ] `scripts/transcript_runner.py`: scripted caller turns → recorded transcript +
      case-file snapshots → deterministic assertions from the scenario file.
- [ ] `make transcript` target body; runs against `FakeAgent` fixtures until
      integration, then the live agent.

## 4. DeepEval harness                                 ⏸ review after this group
- [ ] `evals/adapter.py`: recorded transcript → `ConversationalTestCase`.
- [ ] Metric config: Knowledge Retention, Role Adherence, Conversation Completeness;
      G-Eval rubrics (safety-interrupt, booking-confirmation, photo-findings).
- [ ] `evals/thresholds.py` pinned per requirements; judge `gpt-4o`.
- [ ] `make eval` target body + skip-with-warning on missing `OPENAI_API_KEY`.

## 5. Canaries
- [ ] Fixture transcripts that must FAIL each metric (re-asked zip, persona break,
      ignored gas mention, booking without read-back); a canary passing = harness bug.

## 6. Gates
- [ ] `make lint` + `make test` clean; canary suite red-as-expected.
- [ ] Tick roadmap Phase 1b `[x]` in `specs/constitution/roadmap.md`.

## Integration deltas (lead applies at merge)
- Point `make transcript` / `make eval` from fixture mode to the live agent once
  voice-diagnostic-core merges (integration step 3 in COORDINATION §5).
