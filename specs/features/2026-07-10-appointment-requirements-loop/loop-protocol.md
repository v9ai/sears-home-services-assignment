---
name: appointment-requirements-iterate
description: Run ONE bounded appointment-requirements iteration for the voice agent — measure the hermetic appointment-requirements bench (spec Tier 2 scheduling + Tier 1 never-re-ask probes), pick the single biggest remaining conformance gap, apply one fix with its regression test, validate quality gates, accept or revert, record in the loop ledger. Built on the loop-v2 conventions (lanes, collaborator-dirt rule, decision packets). Designed to be driven by /loop (self-paced); prints APPT_REQ_LOOP CONTINUE or STOP as its final line.
---

# Appointment Requirements Iterate — one loop iteration

You are executing ONE iteration of the appointment-requirements loop. The target
defect class is **spec non-conformance in the appointment/scheduling surface**: the
take-home spec (Tier 2 "Technician Scheduling" + Tier 1 "Conversation Memory",
mirrored in `specs/features/2026-07-08-technician-scheduling/requirements.md`)
requires a seeded technician database, zip+appliance availability matching, a
scheduling flow proposing matching slots, verbal confirmation of the appointment
details before concluding, and never re-asking known facts. The implementation
substantially exists; this loop turns each requirement into a continuously-measured
probe and closes the measured gaps (deterministic read-back check, zip validation,
explicit appliance param, phone offered-slot threading) one fix per iteration.

This loop adopts the v2 conventions from `.claude/skills/latency-maximize/`: work on
`main` with the collaborator-dirt rule, not a fictional branch; eval failures must
reproduce to count; human-decision items produce packets and `awaiting-human`, never
dead stops. All hard-gate probes are deterministic and keyless — there is no noise
protocol in this loop.

Durable state: ledger
`specs/features/2026-07-10-appointment-requirements-loop/loop-ledger.md` (read it
first, trust it over memory, update it last). Iteration 1 (`q1`) commits a protocol
copy to `specs/features/2026-07-10-appointment-requirements-loop/loop-protocol.md` —
on any drift between this file and that one, the committed copy wins.

FINAL output line, exactly one of:

    APPT_REQ_LOOP: CONTINUE (iteration <N> done: <fix-id> <accepted|reverted|blocked|awaiting-human>; next: <fix-id>)
    APPT_REQ_LOOP: STOP (<reason>)

When driven by `/loop`: on CONTINUE schedule the next wakeup immediately (iterations
are hermetic; the pacing bound is `make test`, ~8 min). On STOP end the loop
(ScheduleWakeup stop). If invoked while the ledger says `stopped`, exit at §1 with
zero side effects.

Canonical references (read as needed, don't restate):
- Spec matrix (requirement → probe → owning fix):
  `specs/features/2026-07-10-appointment-requirements-loop/requirements.md`
- Tier 2 as-built truth: `specs/features/2026-07-08-technician-scheduling/requirements.md`
- Bench: `scripts/appointment_requirements_bench.py`, pinned by
  `tests/test_appointment_requirements_bench.py`
- Scheduling surfaces: `app/tools/scheduling_tools.py`, `app/db/matching.py`,
  `app/db/seed.py`, `app/agent/prompts.py` (`SCHEDULING_CONTRACT`)
- Assertions + scenarios: `evals/assertions.py`, `evals/scenarios/schema.py`,
  `evals/scenarios/scheduling/`, `evals/scenarios/canaries/booking_no_readback.yaml`
- Tests to keep green: `tests/scheduling/` (esp. `test_booking_integrity.py` — atomic
  slot claim), `tests/test_prompts_scheduling.py`, `tests/test_assertions.py`

## §0 Invariants (checked on every accept; violating ANY is a hard reject)

1. **Never weaken a probe budget or flip an `enforced` flag to make a run pass** —
   an `enforced` flip happens ONLY in the same commit as the fix that earns it;
   budget changes are human-only.
2. **Stay off the booking-quality loop's live surfaces**: that loop
   (`specs/features/2026-07-10-booking-quality-loop/`, state `running`) owns live
   conversation-quality tuning. Never edit `evals/adaptive_driver.py` or
   `scripts/booking_quality_bench.py`; never edit prompt prose beyond what a fix-id
   names.
3. **Atomic slot claim and never-re-ask stay green**:
   `tests/scheduling/test_booking_integrity.py` and
   `tests/test_prompts_scheduling.py` must pass on every accept.
4. Never touch `.env`. Never weaken/delete failing tests to pass gates. No schema
   change without an Alembic revision.
5. One fix per iteration, minimal diff, regression test in the SAME commit,
   `git revert` (never reset) on reject — history stays bisectable.

## §1 Preconditions (abort loudly; never repair silently)

1. Ledger `state: stopped (…)` → `APPT_REQ_LOOP: STOP (already stopped: <reason>)`.
   No ledger → iteration 1.
2. **Branch = `main`.** Iterations are identified by commit-message prefix
   `appt-req-loop i<N>:`, greppable and bisectable.
3. **Collaborator-dirt rule**: read `git status --porcelain`. Proceed iff the dirty
   files do NOT intersect this iteration's planned fix surface; list them in the
   ledger entry. If they DO intersect → pick the next queue item whose surface is
   clean; if none → STOP (surface contention — human intervention). Stage at hunk
   level when a shared file (e.g. `Makefile`) carries collaborator edits.
4. Keys: none for the bench (hermetic by design). Eval, when mandatory (§6), needs
   judge keys from `.env` (`set -a; source .env; set +a`); a judge-key SKIP counts
   as NOT RUN and rejects a mandatory case.
5. Cost caps (ledger header): `iteration > 12` → STOP (cost-cap);
   `judged_eval_runs_total >= 6` → STOP (cost-cap).

## §2 MEASURE

1. **Hermetic guard first**: `.venv/bin/pytest tests/test_prompts_scheduling.py
   tests/scheduling/test_schema.py tests/test_assertions.py
   tests/test_scenario_schema.py tests/test_appointment_requirements_bench.py -q`
   (all keyless/DB-less). Red → STOP (tree already broken).
2. **Bench**: `make appt-req` → `data/appt_req/<utc-ts>.json`
   (`bench_runs_total += 1`). All probes are deterministic — single-run, no noise
   protocol. `db_live` is advisory and skipped without `DATABASE_URL`; a skip is
   normal, never a defect.
3. Baseline reuse: the previous iteration's `after_report` is reusable iff it still
   exists and no scheduling/eval surface file changed since; otherwise rerun (the
   bench is free).

## §3 DIAGNOSE

1. Rank failing or un-enforced probes by spec weight: `r_confirm` > `r_match` >
   `r_db_schema`/`r_seed` > `r_flow` > `r_memory` (verbal confirmation is the spec's
   most explicit conversational requirement and was the measurement hole).
2. Choose the fix: worst gap → lane row below → minus ledger entries
   `decision: reverted|blocked|awaiting-human` (a retry requires a NEW hypothesis
   recorded in the ledger).

## §4 LANES + fix queue

Work lanes in order Q → F → H, skipping items the ledger shows done. Within a lane,
reordering requires a recorded rationale.

**Lane Q — measurement & gate quality (build before spending on product fixes):**

| id | What | Class |
|----|------|-------|
| q1 | Build the bench: `scripts/appointment_requirements_bench.py` + `make appt-req` + `tests/test_appointment_requirements_bench.py` (schema §10); spec dir (`requirements.md` matrix + ledger); commit the protocol copy; declare `aiosqlite`; archive the first report | neutral |
| q2 | Deterministic read-back assertion: additive `readback` block on `ScenarioAssert` (`evals/scenarios/schema.py`) + `check_structural_assertions` logic (an agent turn strictly BEFORE the final agent turn must name the technician AND ≥1 date token AND ≥1 time token); wire into `evals/scenarios/hermetic/scheduling/readback_confirmation_details.yaml` and `evals/scenarios/canaries/booking_no_readback.yaml` (`canary_layer: both`); unit tests in `tests/test_assertions.py` style; flip `READBACK_FIXTURE_ENFORCED` in the SAME commit | neutral |

**Lane F — product fixes (one per iteration; regression test same commit; eval
mandatory since all touch `app/` or `evals/`):**

| id | Target sub-check | What |
|----|------------------|------|
| f1 | `r_flow.zip_validation` | `_normalize_zip(zip) -> str \| None` in `app/tools/scheduling_tools.py` (strip; US 5-digit; ZIP+4 → 5); `find_technicians` returns `{"status":"invalid_zip"}` asking to re-confirm instead of silently matching nothing; flip `ZIP_VALIDATION_ENFORCED` same commit; tests beside the existing scheduling-tools tests |
| f2 | `r_confirm.explicit_appliance_param` | `book_appointment` gains optional `appliance_type` param; fallback chain: explicit param → `_infer_appliance_type(issue_summary)` → case-file `appliance_type`; error only when all three miss; one contract sentence updated; flip `EXPLICIT_APPLIANCE_PARAM_ENFORCED` same commit; keep `tests/test_tool_schemas.py` / tool-schema budget green |
| f3 | `r_flow.phone_offered_slots` | Thread offered slots into the phone channel's prompt refresh: `app/voice/processors.py::SystemPromptRefreshProcessor` + `app/voice/bot.py` initial messages call `build_system_prompt(case_file, get_offered_slots(session_id))`; update the `build_system_prompt` docstring's "phone path does not surface them yet"; flip `PHONE_OFFERED_SLOTS_ENFORCED` same commit; test in `tests/voice/` |

**Lane H — human-decision packets (measure inputs, write the packet as a PROPOSAL
block in `specs/features/2026-07-10-appointment-requirements-loop/`, mark
`awaiting-human`, move on — never decide):**

| id | Packet |
|----|--------|
| h1 | Street-address capture: the spec's appointments link customers to technicians, but schema + CaseFile hold only a zip — is zip-level dispatch acceptable for this take-home, or should `customers`/CaseFile gain a street address (Alembic rev + contract + one more re-ask surface)? Packet states both options with schema/prompt cost and the grading-rubric reading. |

Terminal (§9.1 only): `gate-flip` — wire `make appt-req` into `make test` as a hard
gate (`test: stutter appt-req`; bench hard-gate default flips 0→1 with
`APPT_REQ_GATE_HARD=0` as the escape hatch); tick the scheduling line in
`specs/features/2026-07-08-technician-scheduling/validation.md`.

## §5 IMPROVE — exactly ONE fix-id, minimal diff, same-commit regression test

Commit message `appt-req-loop i<N>: <fix-id> — <one line>`.
**Forbidden, no exceptions:** flipping `enforced` without the earning fix; weakening
`SCHEDULING_CONTRACT` or any probe budget; schema changes without an Alembic
revision; renaming existing modules; touching `.env`, `evals/adaptive_driver.py`, or
`scripts/booking_quality_bench.py`; weakening eval thresholds or deleting failing
tests.

## §6 VALIDATE (cheap → expensive)

1. `make lint`
2. Full `make test`. A failure in collaborator-owned files you did not touch:
   record + re-run that file once; if it passes in isolation it does not block —
   say so in the ledger (`known_failing_tests` header field tracks the standing set).
3. Eval: MANDATORY for lane F and for q2 (they touch `app/` or `evals/`);
   `judged_eval_runs_total += 1`. Use `make eval-hermetic`; a failure must reproduce
   on ONE retry of the failing test to count as a regression. Skippable ONLY for
   pure-harness lane-Q diffs with the justification recorded.
4. `make appt-req` rerun → after-report; diff probes against baseline.

## §7 ACCEPT / REVERT

- **Lane F fixes (and q2)**: accept iff the target sub-check flipped fail→pass with
  `enforced: true`; AND no other probe or sub-check crossed PASS→FAIL; AND §0
  invariants hold; AND gates green (reproducible-eval rule). **Eval regression =
  hard reject even if the sub-check improved.**
- **Lane Q (neutral, q1)**: gates green + all probes PASS + report archived. No
  improvement bar.
- **Lane H (packets)**: the packet file exists, is committed, and states its decision
  options with measured inputs — outcome `awaiting-human`.
- On reject: `git revert <sha>`, record the negative finding — what was tried, probe
  deltas, and a hypothesis for why it failed — so §3 never retries it blind.

## §8 RECORD

Append one ledger entry, update header counters, commit (accepts: amend the ledger
into the fix commit; rejects: separate `appt-req-loop i<N>: record <fix-id>
(reverted)` commit; never rewrite shared history).

Ledger header:

```markdown
# Appointment Requirements Loop Ledger
state: running
iteration: <N>
bench_runs_total: <N>
judged_eval_runs_total: <N>
consecutive_all_pass: <N>
lane_no_accepts: {Q: 0, F: 0}
known_failing_tests: <exact ids, or none>
```

Per-iteration entry: `## Iteration <N> — <fix-id> — <ACCEPTED|REVERTED|BLOCKED|AWAITING-HUMAN>`
+ one fenced JSON object:

```json
{
  "iteration": 0,
  "timestamp_utc": "",
  "lane": "Q|F|H",
  "fix_id": "",
  "description": "",
  "baseline_report": "<filename in data/appt_req/>",
  "after_report": "<filename>",
  "target_probe": "",
  "probes_delta": {},
  "collaborator_dirty_files": [],
  "gates": {"lint": "", "test": "", "eval": "", "appt_req_overall": false},
  "decision": "accepted | reverted | blocked | awaiting-human",
  "commit": "",
  "revert_commit": null,
  "notes": ""
}
```

`timestamp_utc` from `date -u +%Y-%m-%dT%H:%M:%SZ`.

## §9 STOP / CONTINUE (checked after RECORD, in order)

1. **Success**: last two bench reports both `overall_pass: true` with every
   sub-check `enforced: true` AND q1–q2 + f1–f3 each accepted (or
   blocked/awaiting-human with a recorded reason) → execute the terminal
   `gate-flip` as one final commit, `state: stopped (success)`,
   `APPT_REQ_LOOP: STOP (requirements PASS x2 fully enforced — gate flipped to hard)`.
2. **Lane-dry**: 2 consecutive no-accepts within a lane closes that lane; move to
   the next lane (do NOT global-stop).
3. **All lanes dry or awaiting-human** → `state: stopped (awaiting-human)`; the STOP
   line names the open packets — a hand-off, not a failure.
4. **Cost caps** (§1.5) → `state: stopped (cost-cap)`.
5. Otherwise CONTINUE, naming the next fix-id.

## §10 Bench spec (what `q1` builds; the probes ARE the metric)

`scripts/appointment_requirements_bench.py` — hermetic, keyless, deterministic; runs
via `make appt-req`; writes `data/appt_req/<utc-ts>.json`; soft gate
(`APPT_REQ_GATE_HARD` default 0) until the terminal gate-flip. Probe functions take
injectable inputs defaulting to production values
(`probe_r_seed(technicians=seed.TECHNICIANS)`,
`probe_r_confirm(contract_text=SCHEDULING_CONTRACT)`, …) so
`tests/test_appointment_requirements_bench.py` can prove each probe detects a
violating input (mutation cases) — a probe can never rot into a tautology.

| Probe | Spec requirement | Check |
|-------|------------------|-------|
| `r_db_schema` | R-DB schema | `metadata.create_all` on throwaway in-memory SQLite + `inspect()`: 6 scheduling tables; `UNIQUE(technician_id, starts_at)` + `status` on `availability_slots`; `appointments` FKs to slot/technician/customer/session with `slot_id` unique; zip index on `service_areas` |
| `r_seed` | R-DB seeding (5–10+ techs, multiple zips/specialties) | static `app.db.seed` constants: ≥5 techs, ≥4 zips across ≥2 metro clusters, all 6 specialties covered, unique emails, ≥7-day slot horizon |
| `r_match` | R-MATCH (zip + appliance → technician) | real `find_technician_matches` on in-memory aiosqlite over a seed-derived dataset with fixed `now`: correct zip∧specialty set, soonest-first, ≤3 slots/tech, unknown zip → `[]`, soft-window fallback, booked/past excluded |
| `r_flow` | R-FLOW (collect availability, propose ≤3 slots) | contract text (≤3 options, zip-first, availability window, slot_id verbatim) + `_render_offered_slots` + matching default 3 + 4 scheduling scenarios load. Sub-checks: `zip_validation` (f1), `phone_offered_slots` (f3) |
| `r_confirm` | R-CONFIRM (verbal read-back before concluding) | contract text (read-back tech+date+time, appointment_id read-back, slot_taken alternatives). Sub-checks: `readback_fixture` (q2 — positive fixture PASSes, no-read-back canary FAILs), `explicit_appliance_param` (f2) |
| `r_memory` | Tier-1 never-re-ask | prompt rules + `check_structural_assertions` passes the committed fixture AND fails a synthetic violating one |
| `db_live` | advisory only | real-Postgres row counts + one matching smoke iff `DATABASE_URL` reachable; skipped ≠ pass; NEVER affects `overall_pass` |

Report JSON:

```json
{
  "schema_version": 1,
  "timestamp_utc": "",
  "probes": {
    "<probe>": {
      "checks": {"<name>": true},
      "<subcheck>": {"enforced": false, "pass": false},
      "budget": {},
      "pass": true
    }
  },
  "advisory": {"db_live": {"status": "skipped|pass|fail", "detail": {}}},
  "overall_pass": true
}
```

`probe.pass` = all plain checks true AND all `enforced: true` sub-checks pass;
`overall_pass = all(probes[*].pass)`; `advisory` never gates. `main()` always writes
the report, prints one verdict line per probe (naming un-enforced sub-checks), and
exits 1 iff failing AND `APPT_REQ_GATE_HARD=1`.
