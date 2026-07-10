# Appointment Requirements Loop Ledger
state: running
iteration: 4
bench_runs_total: 5
judged_eval_runs_total: 2
consecutive_all_pass: 5
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

## Iteration 3 — q2 — ACCEPTED

```json
{
  "iteration": 3,
  "timestamp_utc": "2026-07-10T20:43:00Z",
  "lane": "Q",
  "fix_id": "q2",
  "description": "Deterministic read-back assertion: additive ReadbackAssert on ScenarioAssert (technician + date_tokens + time_tokens, matched case-insensitively in an agent turn strictly before the final agent turn); wired into hermetic readback scenario and booking_no_readback canary (canary_layer eval->both, proving the detector fires); READBACK_FIXTURE_ENFORCED flipped in the same commit; 6 unit tests appended to tests/test_assertions.py.",
  "baseline_report": "20260710T132734Z.json",
  "after_report": "20260710T204300Z.json",
  "target_probe": "r_confirm.readback_fixture",
  "probes_delta": {"r_confirm.readback_fixture": "advisory fail -> ENFORCED pass (positive fixture passes, canary fails)"},
  "collaborator_dirty_files": ["app/main.py", "app/tools/visual_tools.py", "app/uploads/routes.py (in-flight E501s)", "web/ deletions staged by the concurrent bugfix-loop session — commit used explicit pathspecs to avoid sweeping them"],
  "gates": {"lint": "PASS on fix surface (repo-wide blocked by collaborator in-flight E501s in app/uploads/routes.py)", "test": "PASS per §6.2 (1519/1520; tests/latency/test_tts_pipeline.py parallelism timing test failed under two concurrent sessions, passes in isolation — collaborator-owned)", "eval": "PASS per §6.3 (judged; scheduling_slot_conflict rubric flake failed once, passed on retry)", "appt_req_overall": true},
  "decision": "accepted",
  "commit": "appt-req-loop i3: q2",
  "revert_commit": null,
  "notes": "make transcript PASS with the canary now failing structurally as designed. Precondition change: the user checkpoint-committed the working set (8500c66) and authorized full queue execution. NEXT: f1 (zip validation)."
}
```

## Iteration 4 — f1 — ACCEPTED

```json
{
  "iteration": 4,
  "timestamp_utc": "2026-07-10T21:03:52Z",
  "lane": "F",
  "fix_id": "f1",
  "description": "Zip validation: _normalize_zip (strip, ZIP+4 -> 5-digit, reject non-5-digit) in scheduling_tools; find_technicians answers a malformed zip with structured {status: invalid_zip} asking to re-confirm, BEFORE persisting to the case file or searching; ZIP_VALIDATION_ENFORCED flipped same commit; 12 hermetic tests in tests/test_zip_validation.py.",
  "baseline_report": "20260710T204300Z.json",
  "after_report": "20260710T210352Z.json",
  "target_probe": "r_flow.zip_validation",
  "probes_delta": {"r_flow.zip_validation": "advisory fail -> ENFORCED pass"},
  "collaborator_dirty_files": ["app/main.py", "app/uploads/routes.py", "app/tools/visual_tools.py", "web/ staged deletions (concurrent bugfix-loop session) — pathspec commit"],
  "gates": {"lint": "PASS on fix surface", "test": "PASS (1532, includes the previously-flaky tts_pipeline timing test)", "eval": "PASS (judged, 67 passed, no retry needed)", "appt_req_overall": true},
  "decision": "accepted",
  "commit": "appt-req-loop i4: f1",
  "revert_commit": null,
  "notes": "Invalid zip no longer pollutes the case file the never-re-ask contract trusts. NEXT: f2 (explicit appliance_type param)."
}
```
