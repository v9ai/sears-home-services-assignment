# Appointment Requirements Loop Ledger
state: running
iteration: 2
bench_runs_total: 3
judged_eval_runs_total: 0
consecutive_all_pass: 2
lane_no_accepts: {Q: 0, F: 0}
known_failing_tests: none

Protocol: `loop-protocol.md` (committed copy of
`.claude/skills/appointment-requirements-iterate/SKILL.md`; on drift the committed
copy wins). Reports in `data/appt_req/` (gitignored, referenced by filename).
Target: Tier 2 Technician Scheduling spec conformance (R-DB / R-MATCH / R-FLOW /
R-CONFIRM + Tier-1 never-re-ask); spec matrix in `requirements.md`.
Coordination: the booking-quality loop is `state: running` on the live lane — this
loop stays hermetic and off its surfaces (protocol §0.2).

## Iteration 1 — q1 — ACCEPTED

```json
{
  "iteration": 1,
  "timestamp_utc": "2026-07-10T13:12:26Z",
  "lane": "Q",
  "fix_id": "q1",
  "description": "Built the bench (6 hermetic probes + advisory db_live) + make appt-req + 18 bench tests (schema pin, gate wiring, mutation cases) + spec dir (requirements matrix, ledger, protocol copy); declared aiosqlite dev dep; archived first reports.",
  "baseline_report": "20260710T130818Z.json",
  "after_report": "20260710T131340Z.json",
  "target_probe": null,
  "probes_delta": {"all": "first reports — 6/6 PASS; sub-checks advisory: readback_fixture (q2), zip_validation (f1), explicit_appliance_param (f2), phone_offered_slots (f3); db_live SKIPPED keyless / PASS with DATABASE_URL, overall_pass identical (hermeticity proof); APPT_REQ_GATE_HARD=1 exits 0"},
  "collaborator_dirty_files": ["Makefile (latency $(args) hunk left unstaged)", "app/agent/prompts.py", "app/tools/scheduling_tools.py", "tests/test_assertions.py", "tests/test_prompts_scheduling.py", "evals/scenarios/hermetic/ (untracked)", "readback + canary fixtures (untracked)", "~110 more collaborator-dirty/untracked files not on this surface"],
  "gates": {"lint": "PASS (loop files; repo-wide make lint has a pre-existing I001 in collaborator's untracked tests/test_safety_recall.py)", "test": "PASS (stutter gate + 1344 passed)", "eval": "SKIPPED (pure-harness lane-Q diff, no app behavior touched — protocol §6.3)", "appt_req_overall": true},
  "decision": "accepted",
  "commit": "appt-req-loop i1: q1",
  "revert_commit": null,
  "notes": "All six probes green on first measurement — Tier 2 substantially conforms; the loop's remaining value is the four advisory sub-checks. NEXT: q2 (deterministic read-back assertion) — its fixtures/scenarios exist on disk but are untracked collaborator files; q2 stages only the files its fix surface owns."
}
```

## Iteration 2 — h1 — AWAITING-HUMAN

```json
{
  "iteration": 2,
  "timestamp_utc": "2026-07-10T13:27:34Z",
  "lane": "H",
  "fix_id": "h1",
  "description": "Street-address decision packet (h1-street-address-packet.md): zip-only dispatch (spec-literal, zero cost) vs service-address capture (Alembic rev + CaseFile field + contract sentence + fixture updates). Measured inputs: no address field anywhere (contracts.Customer = name/zip/email; rev 0001/0002 schema); spec text matches on zip only.",
  "baseline_report": "20260710T131340Z.json",
  "after_report": "20260710T132734Z.json",
  "target_probe": null,
  "probes_delta": {"all": "unchanged — 6/6 PASS, 4 sub-checks advisory"},
  "collaborator_dirty_files": ["evals/scenarios/hermetic/ (untracked — blocks q2's positive scenario)", "evals/fixtures/transcripts/scheduling_readback_confirmation_details.json (untracked — blocks q2)", "app/tools/scheduling_tools.py (blocks f1, f2)", "app/agent/prompts.py (blocks f2)", "app/voice/bot.py (blocks f3)", "tests/test_assertions.py"],
  "gates": {"lint": "N/A (docs-only diff)", "test": "guard subset PASS (86); full make test PASS at i1, no code changed since", "eval": "SKIPPED (docs-only lane-H diff — protocol §6.3)", "appt_req_overall": true},
  "decision": "awaiting-human",
  "notes": "q2/f1/f2/f3 ALL surface-blocked by collaborator dirt this iteration (§1.3) — h1 was the only clean-surface queue item. UNBLOCK PATH: commit (or discard) the working-tree changes to evals/scenarios/hermetic/, the readback fixture, app/tools/scheduling_tools.py, app/agent/prompts.py, app/voice/bot.py; then q2 is next. h1 closes when a human records A or B under 'Human decisions' here.",
  "commit": "appt-req-loop i2: h1",
  "revert_commit": null
}
```
