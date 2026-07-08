# Call Recording & In-App Replay — Validation

## Automated
- [x] API tests: `/api/recordings` newest-first with limit/offset; `/api/recordings/{id}` returns
      transcript with `has_audio` flags + case file; audio endpoint serves bytes with
      the right content-type and 404s cleanly on missing seq/session; all with **no
      auth headers**. `tests/test_recordings_routes.py` (green offline; skips loudly
      without a migrated Postgres per `db_session` semantics).
- [x] Recorder unit: write failure is swallowed + logged (live call unaffected).
      `tests/test_ws_recording_hooks.py::test_scripted_ws_turn_write_failure_swallowed_and_logged`.
- [x] Backward compat: a pre-feature transcript (entries without `ts`/`audio_seq`)
      lists and replays text-only without error. Covered in both
      `tests/test_recordings_routes.py` and `tests/test_ws_recording_hooks.py`.
- [x] Recording hook: scripted WS turn produces transcript `ts` + on-disk audio files
      matching `audio_seq`s. `tests/test_ws_recording_hooks.py::test_scripted_ws_turn_records_ts_and_matching_audio`.
- [x] Full existing suite green unchanged (recording alters no agent behavior). 240
      passed with the local Postgres unreachable/unmigrated (see note below); no
      pre-existing test regressed.
- [ ] `make lint` + `make test` + `make transcript` clean. `make lint` is clean.
      `make test` is currently **not** clean, but the recordings feature is not the
      cause: `tests/scheduling/conftest.py`'s `autouse=True` `_fresh_schema` fixture
      runs `DROP SCHEMA public CASCADE` + a minimal `create_all` (id/customer_id-only
      stand-ins for `customers`/`sessions`) directly against the shared `DATABASE_URL`
      before every technician-scheduling test — not an isolated test DB. Any test
      collected after `tests/scheduling/` in the same `pytest tests` run (including
      `tests/test_recordings_routes.py`) then hits a destroyed/under-migrated schema.
      Confirmed: `tests/test_recordings_routes.py` alone passes/skips cleanly (4
      passed, 7 skipped without a migrated DB); it only fails inside the full suite,
      immediately after a fresh `alembic upgrade heads` + `make seed` gets wiped by
      that fixture. This is a pre-existing bug in an already-shipped feature
      (technician-scheduling), out of scope for this team to fix unilaterally —
      flagged to the user. `make transcript` not yet run pending resolution.

## Manual
1. Make a web call (chat page, a few turns) → click the "Recordings" nav link → the
   **dedicated page lists every call ever made (both channels)** for any user with no
   auth; the new call is at the top; **quick-play works from the list row**, and the
   detail view replays the agent audio in order with transcript highlighting; typed
   caller turns render as text.
2. After the phone channel is live: make a phone call → replay shows both sides
   (caller wav + agent audio).
3. Open `/recordings` from an incognito/second browser with no credentials — full access
   (the no-auth directive), and the README known-limitations privacy note exists.
4. Restart the app container — recordings persist (named volume).

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates green; manual web-call replay (item 1) completed.
- [ ] Integration deltas applied (router mount, hooks, volume, README note).
- [ ] Deferred scope (retention, search, auth, full-duplex capture) recorded above.
- [ ] Roadmap Phase 7 ticked `[x]`.
