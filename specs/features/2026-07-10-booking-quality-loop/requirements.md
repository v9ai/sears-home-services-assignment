# Booking quality loop (live conversation reliability) — Requirements

## Source
Pasted requirement (not from the roadmap):
> Design a claude code loop which can iterate over this issue and improve max
> possible with high quality. — "This issue" (2026-07-09/10 live evidence, recorded
> in `2026-07-09-slot-reference-robustness/` and roadmap Phase 11): the live agent's
> conversation reliability is far below what the all-green offline gates imply.
> Observed on real drives: never-re-ask violations ("which appliance?" with the case
> file populated), lost slot lists ("I don't see the list of available slots"),
> confirm→re-find loops instead of booking, invented tool ids, and raw-dict tool
> args. Unit tests and the fixture-based `make eval` structurally cannot see any of
> this; only adaptive live drives can.

## Scope

### Included
- **Measurement harness** (the loop's `make latency` equivalent):
  - `evals/adaptive_driver.py` — a deterministic adaptive caller: a keyword
    reply-policy state machine reacts to the agent's last utterance and drives the
    REAL agent (`run_turn`) turn-by-turn with a bound session, so live drives are
    reproducible without a human. Emits per-drive metrics (booked, turns-to-book,
    reasks via the existing `detect_reasks`, tool errors via the bench wiretap,
    attribution via `appointments_booking_probe`).
  - `scripts/booking_quality_bench.py` — runs the pinned six-scenario matrix
    sequentially, scores each against its success rule, writes
    `data/booking_quality/<utc-ts>.json` with `overall_pass`, supports
    `--compare <before.json>`, exits 0/1. Self-cleaning: every row it creates
    (appointments, customers, sessions) is deleted and every slot it claims is
    reopened in a `finally` block — the shared dev DB is left byte-identical.
  - `make booking-bench` target.
- **Scenario matrix** (pinned; zips chosen against the committed seed):
  | id | shape | success rule |
  |---|---|---|
  | `happy_upfront` | dishwasher @ 60601, all details in turn 1 | booked ≤ 4 turns, attributed, 0 reasks |
  | `drip_fed` | washer @ 60614, details only when asked | booked ≤ 7 turns, attributed, 0 reasks |
  | `reask_trap` | washer @ 60601, every fact in turn 1 | booked, **0 reask violations** |
  | `no_coverage` | dishwasher @ 60614 (no tech in seed) | agent reports no coverage honestly, **no booking row**, no invented tech |
  | `slot_conflict` | oven @ 60642; bench books the first offered slot out-of-band before the caller accepts | agent relays `slot_taken`, re-offers, books an alternative |
  | `safety_interrupt` | oven + "I smell gas" mid-call | `safety_flag` set, no further troubleshooting, technician offered |
- **Bench targets** (the loop's budgets — changing them is a human decision):
  all 6 scenario rules pass · aggregate `tool_exception_count == 0` ·
  `unknown_id_errors == 0` · every booked row attributed (`session_id` set).
- **The loop skill** `.claude/skills/booking-quality-iterate/SKILL.md` — ONE bounded
  iteration per invocation, driven by `/loop` self-paced, mirroring
  `latency-iterate`'s protocol: preconditions → measure → diagnose → ONE fix with
  its regression test → full gates → accept/revert → ledger → CONTINUE/STOP.
  Durable state in `specs/features/2026-07-10-booking-quality-loop/loop-ledger.md`.
- **Seeded fix queue** (provenance = the 2026-07-09/10 live evidence; the loop
  re-ranks from each bench report): offer-memory (slot offers survive turns
  structurally, like the case file) · pending-booking contract (yes ⇒ book, never
  re-find) · captured-facts echo hardening (the "which appliance?" violation) ·
  tool-arg guards on the remaining tools · model A/B decision record ·
  terminal `eval-live-gate` wiring (testing-evals group 7's owed piece).
- Hermetic tests for the policy/scoring/report shape (no DB, no LLM).

### Not included (deferred)
- Phone-channel (Pipecat) adaptive drives — the web `run_turn` path shares prompts
  and tools; audio-loop driving needs the synthetic-caller rig (telephony feature).
- Changing the shipped model default — the loop may RECORD an A/B; flipping the
  default is a human decision like every provider change.
- Loosening bench targets to make a run pass (forbidden, mirrors the latency loop).

### Contract shapes
- New files only, plus one `Makefile` target; no schema change; no frozen-contract
  change. Source-of-truth: `evals/adaptive_driver.py`,
  `scripts/booking_quality_bench.py`, `.claude/skills/booking-quality-iterate/`.
- Pipeline / build target: `make booking-bench` (live, keyed) ·
  `make lint`/`make test` (hermetic gates).

## Decisions
1. **Adaptive drives, not more fixtures** — every defect this loop targets was
   invisible to canned transcripts; a deterministic reply policy makes live drives
   repeatable enough to diff run-over-run while still exercising the real model.
2. **One fix per iteration, regression test in the same commit** — proven by the
   latency loop; keeps history bisectable and the accept/revert decision clean.
3. **Self-cleaning bench** — the shared dev DB is also the demo DB; the 2026-07-09
   manual-gate session left rows behind and broke 14 recordings tests (fixed since).
   The bench must never leave state.
4. **Run on the current branch; never create/switch branches** — this working tree
   is shared with parallel sessions (shared-tree constraint observed 2026-07-09/10);
   branch switching would break them. Deviation from the latency loop recorded here.
5. **Deploy path**: no deploy — harness + skill + specs.
6. **Gate path**: hermetic tests + `make lint`/`make test`; the bench itself is the
   loop's measured gate (keyed, counted against the cost cap).

## Architecture impact
- Component / plane touched: eval harness, bench scripts, agent prompts/tools (only
  via future loop iterations, each under this spec's queue).
- **Invariant-preserving**: no constitution bullet changes; the model-provider
  boundary and frozen tool contracts stay untouched by the loop itself.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; sibling loop:
  `.claude/skills/latency-iterate/` + its ledger (protocol provenance).
- Constraints: cost caps (iteration ≤ 10, bench_runs_total ≤ 24); `make eval`
  mandatory for any prompt/tool diff; never touch `.env`; never run two live benches
  concurrently.
- Open questions / explicit deferrals: none beyond "Not included".
