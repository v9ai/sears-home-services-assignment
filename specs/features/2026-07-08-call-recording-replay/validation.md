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
- [x] Full existing suite green unchanged (recording alters no agent behavior). 247
      passed against the migrated local Postgres (see note below); no pre-existing
      test regressed.
- [x] `make lint` + `make test` + `make transcript` clean. Found (and fixed, with
      user sign-off) a pre-existing bug blocking this: `tests/scheduling/conftest.py`'s
      `autouse=True` `_fresh_schema` fixture ran `DROP SCHEMA public CASCADE` directly
      against the shared `DATABASE_URL` before every technician-scheduling test,
      destroying the migrated schema (and any seed data) for every test collected
      after it in the same `pytest` run — including `tests/test_recordings_routes.py`.
      Fixed by isolating that fixture to a dedicated `<db>_test_scheduling` database
      on the same Postgres server (created on demand), never the shared app database.
      Unrelated to the recordings feature itself; not this feature's regression.
      After the fix and a fresh `alembic upgrade heads` + `make seed`: `make lint`
      clean, `make test` 247 passed, `make transcript` 26/26 scenarios PASS.

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
- [x] Each "Included" scope bullet in `requirements.md` is observably true (verified
      by code + automated tests; live-browser confirmation still pending, see below).
- [ ] All automated gates green; manual web-call replay (item 1) completed. Automated
      gates ARE green; manual item 1 (and 2-4) still need a live browser + running
      backend — not performable by this pass.
- [x] Integration deltas applied (router mount, hooks, volume, README note). Router
      mounted in `app/main.py`, hooks present in `app/ws/routes.py` /
      `app/phone/real_agent.py` / `app/phone/routes.py`, `recordings` named volume in
      `docker-compose.yml`, README `REPLAY_TTS_FALLBACK` line corrected.
- [x] Deferred scope (retention, search, auth, full-duplex capture) recorded above
      (see `requirements.md` "Not included (deferred)").
- [ ] Roadmap Phase 7 ticked `[x]` — held pending the manual live-replay check above.
