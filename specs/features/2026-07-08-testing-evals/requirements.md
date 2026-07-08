# Testing & Evals Harness — Requirements

## Source
Roadmap Phase 1b (specs/constitution/roadmap.md); `tech-stack.md` → Evaluation.
Assignment §6 ("working software", caller-experience quality) demands the quality
gates be real, not aspirational: this feature builds the pytest + transcript + DeepEval
machinery every other feature's `validation.md` invokes.

## Scope

### Included
- **pytest scaffolding** (`tests/`): async fixtures (event-loop, DB session against the
  Compose `db`, per-test rollback), a `FakeLLM`/`FakeAgent` fixture for tool unit tests,
  factory helpers for seeded technicians/sessions.
- **Transcript runner** (`scripts/transcript_runner.py`, `make transcript`): drives the
  agent with scripted caller turns from `evals/scenarios/*.yaml`, records the full
  conversation + case-file snapshots, applies each scenario's deterministic assertions
  (facts captured, no repeated question, safety routing, booking row).
- **DeepEval harness** (`evals/`, `make eval`): adapts recorded transcripts into
  `ConversationalTestCase`s; metric config + pinned thresholds; per-feature G-Eval
  rubrics; judge `gpt-4o`.
- **Scenario matrix** (`evals/scenarios/`): per appliance (×6) — happy diagnostic ·
  safety escalation · error-code/model capture; scheduling — happy booking ·
  no-tech-in-zip · slot-conflict · zip-never-re-asked; visual — email spell-back ·
  post-upload incorporation. ≈ 24 scenarios; scheduling/visual scenarios are marked
  `requires: [scheduling|visual]` and skip until those features merge.
- **Failure canaries**: fixture transcripts that MUST fail each metric (a re-asked zip,
  a persona break, an ignored gas mention) proving the gate can actually go red.
- **CI behavior**: `make eval` skips-with-warning when `OPENAI_API_KEY` is absent;
  `make test` + `make transcript` (structural layer) never skip.

### Not included (deferred)
- Phone-channel audio-level evals (latency/word-error on μ-law audio) — backlog.
- Load/perf testing; security scanning — out of take-home scope.

### Contract shapes
- Scenario YAML: `{id, feature: core|scheduling|visual, requires: [], turns:
  [{caller: str}], assert: {facts: {...}, no_reask: [...], safety_interrupt: bool,
  booking_row: bool}, eval: {metrics: [...], rubrics: [...]}}`.
- Thresholds (pinned in `evals/thresholds.py`): Knowledge Retention ≥ 0.8 ·
  Role Adherence ≥ 0.7 · Conversation Completeness ≥ 0.7 · G-Eval rubrics
  (safety-interrupt, booking-confirmation, photo-findings) ≥ 0.8; a miss fails the gate.
- Gates: `make test` (harness self-tests), `make transcript`, `make eval`.

## Decisions
1. **DeepEval as the eval framework (user directive, 2026-07-08)** — pytest-native, its
   conversational metrics map 1:1 onto the mission non-negotiables (Knowledge Retention
   = never-re-ask), and G-Eval covers the feature-specific rubrics without custom judge
   plumbing.
2. **Scenarios as YAML fixtures, shared by both gates** — one scenario file drives the
   deterministic transcript assertions AND the DeepEval judgment; no drift between the
   two layers.
3. **Canaries are mandatory** — a gate that has never failed proves nothing; each metric
   ships with a fixture transcript that must go red.
4. **Determinism posture** — scenario runs use temperature 0 and pinned model ids;
   judged metrics tolerate variance via thresholds, structural assertions do not.
5. **Gate path**: `make test` + `make transcript` + `make eval` (this feature IS the
   gate path).

## Architecture impact
- Adds `tests/`, `evals/`, `scripts/transcript_runner.py`; fills the `test`,
  `transcript`, `eval` Makefile target bodies (declared as integration deltas if the
  foundation stubs change). Invariant-preserving.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md` → Evaluation;
  `specs/constitution/COORDINATION.md` §3–4 (owned paths; fixture-transcript stub seam).
- Parallel start: develops against recorded fixture transcripts + canaries; must not
  import `app.agent`. Flips to live agent runs at integration step 3.
- Constraints: `make eval` never silently green; skips only on missing key, loudly.
