# Stutter Loop Ledger
state: running
iteration: 2
judged_eval_runs_total: 0
consecutive_all_pass: 2
lane_no_accepts: {Q: 0, F: 0}
known_failing_tests: none

Protocol: `loop-protocol.md` (committed copy of `.claude/skills/stutter-iterate/SKILL.md`;
on drift the committed copy wins). Reports in `data/stutter/` (gitignored, referenced by
filename). Target defect: the 2026-07-09 barge-in echo loop
(docs/local-twilio-run.md "Stuttering during the reply").

## Iteration 2 — q2 — ACCEPTED

```json
{
  "iteration": 2,
  "timestamp_utc": "2026-07-10T05:22:48Z",
  "lane": "Q",
  "fix_id": "q2",
  "description": "scripts/call_audio_report.py — offline stereo-WAV stutter analyzer (bot = right channel): mid-reply gaps > 250 ms, restart detection via normalized cross-correlation of the post-gap head against the pre-gap reply (up to 5 s back), per-call JSON verdict clean|stutter-suspect. tests/test_call_audio_report.py: 9 tests on synthetic seeded-noise WAVs (clean, gap, restart, non-restart gap, prosody pause, empty, right-channel isolation, dir scan, absence).",
  "baseline_report": "20260710T050440Z.json",
  "after_report": "20260710T051740Z.json",
  "target_probe": null,
  "probes_delta": {"all": "unchanged, all PASS (no app/voice code touched); pacing max_gap median 42.31 -> 40.71ms within noise"},
  "pacing_noise_pct": 2.7,
  "live_evidence": "analyzer run on data/recordings: calls_analyzed=0 (no call.wav yet — only per-line web-channel WAVs from 2026-07-08; evidence lane armed for the next real call)",
  "collaborator_dirty_files": ["evals/adaptive_driver.py", "evals/test_library_live.py", "pyproject.toml", "specs/features/2026-07-08-testing-evals/requirements.md", "tests/test_booking_quality_policy.py", "tests/voice/test_bargein_guard.py", "tests/test_eval_gate_split.py (untracked)"],
  "gates": {
    "lint": "PASS",
    "test": "PASS (618 passed, 0 failed — full suite; hermetic guard FILLER_ENABLED=0, 144 passed)",
    "eval": "SKIPPED (pure-harness lane-Q diff: analyzer script + its tests; no app/ code touched)",
    "stutter_overall": true
  },
  "decision": "accepted",
  "commit": "stutter-loop i2: q2 (git log --grep)",
  "revert_commit": null,
  "notes": "Restart detector v1 (tail-vs-head at the gap) was wrong — a restart replays from EARLIER in the reply, not the cut point; rewritten as post-gap-head searched across the pre-gap region with sliding-norm normalization (caught by the synthetic-restart test before commit). Next: q3 (storm tripwire log_event in the serializer — touches app/voice/serializer.py, eval-hermetic will be mandatory)."
}
```

## Iteration 1 — q1 — ACCEPTED

```json
{
  "iteration": 1,
  "timestamp_utc": "2026-07-10T05:10:36Z",
  "lane": "Q",
  "fix_id": "q1",
  "description": "Build the hermetic stutter bench: scripts/stutter_bench.py (echo_storm / clear_accounting / phantom_tail / pacing probes), make stutter target, tests/test_stutter_bench.py (6 tests), ledger + committed protocol copy.",
  "baseline_report": null,
  "after_report": "20260710T050440Z.json",
  "target_probe": null,
  "probes_delta": {
    "echo_storm": "PASS (0/6 echo events opened a turn; genuine 5-word barge-in honored)",
    "clear_accounting": "PASS (clears == genuine interruptions)",
    "phantom_tail": "ADVISORY PASS — tail_echo_turns_opened=1 measured: a 1-word trailing echo right after BotStoppedSpeaking opens a phantom turn today. This is f1's quantified target.",
    "pacing": "PASS (cadence 40ms, max_gap median 42.31ms vs 120ms budget, noise 2.7%, 0 gaps >2x cadence)"
  },
  "pacing_noise_pct": 2.7,
  "live_evidence": null,
  "collaborator_dirty_files": ["tests/voice/test_bargein_guard.py (import-order cosmetics; not in q1 surface)"],
  "gates": {
    "lint": "PASS",
    "test": "PASS (602 passed, 0 failed — full suite; hermetic guard run with FILLER_ENABLED=0, 144 passed)",
    "eval": "SKIPPED (pure-harness lane-Q diff: bench script + Makefile target + bench tests + specs; no app/ code touched)",
    "stutter_overall": true
  },
  "decision": "accepted",
  "commit": "stutter-loop i1: q1 (git log --grep)",
  "revert_commit": null,
  "notes": "FINDING for a future lane item: run_bot's missing-Twilio-creds 'degraded mode' (app/voice/bot.py — logs twilio.serializer.autohangup_disabled and proceeds) would actually raise in pipecat 1.5: TwilioFrameSerializer validates call_sid/account_sid/auth_token at __init__ when auto_hang_up (default True). The bench works around it with InputParams(auto_hang_up=False). Production always has creds so it is latent, but the log line lies about the failure mode. Candidate: pass auto_hang_up=False explicitly when creds are missing. Also noted: the latency loop's q0-3 eval split (make eval-hermetic / eval-live) has landed — lane-F iterations use make eval-hermetic as the mandatory gate. Next: q2 (call_audio_report.py — offline stereo-WAV gap/restart analyzer)."
}
```
