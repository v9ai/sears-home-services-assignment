# Call Recording & In-App Replay — Validation

## Automated
- [ ] API tests: `/api/calls` newest-first with limit/offset; `/api/calls/{id}` returns
      transcript with `has_audio` flags + case file; audio endpoint serves bytes with
      the right content-type and 404s cleanly on missing seq/session; all with **no
      auth headers**.
- [ ] Recorder unit: write failure is swallowed + logged (live call unaffected).
- [ ] Backward compat: a pre-feature transcript (entries without `ts`/`audio_seq`)
      lists and replays text-only without error.
- [ ] Recording hook: scripted WS turn produces transcript `ts` + on-disk audio files
      matching `audio_seq`s.
- [ ] Full existing suite green unchanged (recording alters no agent behavior).
- [ ] `make lint` + `make test` + `make transcript` clean.

## Manual
1. Make a web call (chat page, a few turns) → open `/calls` → the call is listed →
   replay plays the agent audio in order with transcript highlighting; typed caller
   turns render as text.
2. After the phone channel is live: make a phone call → replay shows both sides
   (caller wav + agent audio).
3. Open `/calls` from an incognito/second browser with no credentials — full access
   (the no-auth directive), and the README known-limitations privacy note exists.
4. Restart the app container — recordings persist (named volume).

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates green; manual web-call replay (item 1) completed.
- [ ] Integration deltas applied (router mount, hooks, volume, README note).
- [ ] Deferred scope (retention, search, auth, full-duplex capture) recorded above.
- [ ] Roadmap Phase 7 ticked `[x]`.
