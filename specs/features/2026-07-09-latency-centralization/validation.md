# Latency Centralization — Validation

## Automated

- [x] `make lint` — ruff check + format clean (2026-07-09).
- [x] `make test` — full suite green: 439 passed (2026-07-09).
- [x] `.venv/bin/pytest tests/latency tests/voice tests/phone tests/test_latency_bench.py tests/test_latency_probe.py -q` — 165 passed (2026-07-09).
- [x] `make latency` without API keys — skip-loud WARNING, exit 0 (unchanged gating).
- [x] Sync tests specifically:
  - `tests/latency/test_budget_spec_sync.py::test_spec_table_matches_module` — the
    `specs/latency/budgets.md` table and `ALL_BUDGETS_MS` are dict-equal.
  - `test_spec_contract_table_names_exist` — every test named in the
    latency-engineering contract table exists in `tests/latency/`.

## Manual spot-checks

- [x] `grep -rn "2500\|4000" app scripts --include="*.py"` — e2e budget literals only
  in `app/latency/budgets.py` (plus one explanatory comment in the bench header).
- [x] Budget numbers in `specs/` and `docs/` prose appear only in
  `specs/latency/budgets.md`, the historical *measured* RCA tables, and the pinned
  `docs/technical-design.md` summary rows (covered by the sync test).
- [ ] Report artifact: run `make latency` with keys → `data/latency/{ts}.json` has
  `schema_version: 2`, per-channel `budgets_ms` keys, and `budget_p50_ms`/
  `budget_p95_ms` inside each e2e summary.

## Fix-specific regression proof (each maps to a test)

| Fix | Test |
|---|---|
| monotonic clock | `tests/voice/test_voice_metrics.py::test_uses_monotonic_clock` |
| speech-resume timer reset | `::test_user_resuming_speech_resets_timer` |
| abandoned-turn no-leak | `::test_abandoned_turn_does_not_leak_into_next` |
| bounded dedup set | `::test_seen_frame_ids_bounded` |
| web budget gating | `tests/test_latency_bench.py::test_web_e2e_gated_by_web_budget` |
| VAD floor logging | `tests/voice/test_vad_config.py::test_vad_stop_secs_below_floor_logs_warning` |
