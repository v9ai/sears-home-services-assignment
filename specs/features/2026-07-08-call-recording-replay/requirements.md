# Call Recording & In-App Replay (all calls, no auth) — Requirements

## Source
User directive (2026-07-08):
> need a way to record all calls and be able to replay in the app for all users no auth

Builds on Phase 1's session persistence — `sessions.transcript` jsonb records every
turn `{role, text}`. On the **web** channel this is written by
`app/agent/session_store.py:persist_session` (called from `app/ws/routes.py`,
unchanged). The **phone** channel now runs the Pipecat pipeline (`app/voice/`, the
`2026-07-09-pipecat-voice-port/` port that replaced the hand-rolled media loop); per-call
history is owned by the Pipecat context aggregator, and wiring the live phone turn path
back into `sessions.transcript` is a deferred follow-up (see that spec's "Not included").
This feature adds per-turn timing + audio capture, a read-only calls API, and a replay
UI.

## Scope

### Included
- **Recording — additive, no migration.** Transcript entries gain optional `ts`
  (ISO-8601) and `audio_seq` (int) keys (jsonb — old sessions stay valid, replay
  text-only). Agent TTS audio is persisted **at synthesis time** (the bytes already
  flow through the app; zero extra API calls) to
  `{RECORDINGS_DIR}/{session_id}/{seq}.{mp3|wav}` — the **web** channel stores the mp3 it
  already synthesizes (unchanged, `app/ws/routes.py`). On the **phone** channel the old
  per-turn wav hooks (`app/phone/real_agent.py`, `app/phone/routes.py:_close_out_turn`)
  are **superseded** — those modules were deleted by the Pipecat port. Full-call phone
  audio is now captured **natively by Twilio** via `<Start><Recording channels="dual">`
  (`app/phone/twiml.py`, retained; see the Twilio Recordings bullet below). Per-turn
  phone-audio capture from Pipecat frames (a Pipecat recorder/observer in `app/voice/`)
  is a **follow-up** — it does not yet exist; today the native Twilio recording covers
  the phone channel's full-call audio and the web hooks cover per-turn web audio. Web
  caller turns are text-only (typed; no audio exists). Recording is **always-on for all
  channels** — that is the directive.
- **Calls API — read-only, no auth**:
  - `GET /api/recordings?limit=&offset=` → newest-first
    `[{id, channel, started_at, ended_at, appliance_type, turn_count}]`
  - `GET /api/recordings/{id}` → full transcript (each turn: role, text, `ts?`,
    `has_audio`) + final case file
  - `GET /api/recordings/{id}/audio/{seq}` → the audio file (correct content-type; 404 when
    absent)
- **Dedicated Recordings page (`web/app/recordings/`) — the feature's centerpiece**:
  - **`/recordings`** — a top-level page, permanently reachable via a **"Recordings"
    nav link in the chat page header** (discoverable, not URL-only), open to all
    users with no auth. Lists **ALL recordings across both channels**, newest first:
    channel badge (web/phone), date+time, appliance, duration, turn count, an
    **inline quick-play** (play-all straight from the row), and a link to the detail
    view. Paginated (limit/offset, matching the API).
  - **`/recordings/[id]`** — the full replay view: transcript bubbles, **play-all**
    sequential audio reusing `web/lib/audioQueue.ts`, per-turn play buttons,
    text-only turns rendered inline with `ts` gaps honored; final case-file panel
    (reuse the chat page's `CaseFilePanel`).
- Optional fallback: turns without stored audio may be re-synthesized on demand behind
  `REPLAY_TTS_FALLBACK` (default **off** — no surprise API spend).
- Storage: `RECORDINGS_DIR=data/recordings` on a Docker named volume `recordings`
  (Docker-volume storage decision precedent; object storage remains rejected).

- **Twilio Recordings — the phone channel's full-call audio (user directive
  2026-07-08, retrieval path verified live same day).** For every REAL inbound call,
  Twilio records the whole call natively: the inbound TwiML emits `<Start><Recording
  channels="dual">` ahead of `<Connect><Stream>` (`app/phone/twiml.py`, retained by the
  Pipecat port), gated by `TWILIO_CALL_RECORDING_ENABLED` (default on). `<Start>` runs
  asynchronously and never blocks the Media Stream, so it is best-effort by construction
  (a recording failure never touches the call) and uses the container's existing
  `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`. Twilio stores the authoritative full-call
  audio (both legs, incl. caller speech we otherwise only have per-utterance).
  - Linkage: `sessions.call_sid` (nullable, migration `0004_call_sid`); the `call_sid`
    is surfaced by the Pipecat route (`app/voice/routes.py`, read from Twilio's `start`
    message and passed to `bind_call_context`/`run_bot`). Persisting it onto the live
    phone session row is part of the deferred phone-session persistence follow-up
    (`2026-07-09-pipecat-voice-port/` "Not included"). The recordings detail API still
    enriches phone sessions with `twilio_recording: {sid, duration, channels}` by
    querying Twilio by `call_sid` at request time.
  - Replay: `GET /api/recordings/{id}/twilio-audio` — server-side authenticated proxy
    streaming the Twilio media (`…/Recordings/{RE}.mp3`); Twilio credentials never
    reach the browser. The `/recordings/[id]` page shows a "full call (Twilio)"
    player for phone sessions alongside the per-utterance app audio.
  - Verified mechanics (2026-07-08, real account): `twilio api:core:recordings:list`
    → recording `REb35d…` (55 s, source OutboundAPI) → authenticated media download
    → valid MP3 (216 KB). CLI runbook rows added to the twilio-cli-debug spec.
  - **Recorded limitation**: synthetic/protocol-level calls with no PSTN leg (e.g. the
    offline pipeline tests in `tests/voice`) can NEVER appear in Twilio Recordings;
    app-side per-turn audio remains the web channel's mechanism, and Twilio's native
    recording (plus the deferred per-turn Pipecat capture) is the phone channel's.
  - Cost/retention: Twilio storage billed per minute-month; deletion policy out of
    scope (consistent with this spec's retention deferral).

### Not included (deferred)
- Per-turn phone-audio capture from the Pipecat pipeline (a recorder/observer over
  `app/voice/` audio frames) — not yet built; native Twilio full-call recording covers
  the phone channel today.
- Raw full-duplex phone audio (barge-in overlap capture) — the native Twilio full-call
  recording is the phone channel's fidelity; per-utterance files remain the web channel's.
- Retention/deletion policies, search/filtering, export, pagination UI beyond
  limit/offset.
- Auth — **explicitly rejected by the directive**; see Decision 2.

### Contract shapes
- Transcript entry: `{role: "user"|"agent", text: str, ts?: str, audio_seq?: int}`.
- Audio file convention: `{RECORDINGS_DIR}/{session_id}/{audio_seq:05d}.{mp3|wav}` —
  derivable, no new table; the list endpoint reads `sessions` (add an index on
  `started_at` only if listing measurably slows).
- Env: `RECORDINGS_DIR=data/recordings`, `REPLAY_TTS_FALLBACK` (default off).
- Compose: named volume `recordings:/app/data/recordings` on the `app` service.
- Gates: `make lint`, `make test` (API + recording-hook + backward-compat units),
  `make transcript` unaffected.

## Decisions
1. **Store-at-synthesis over re-synthesize-at-replay** — on the web channel the audio
   bytes already pass through `_speak`, so persisting them is free and replay is
   byte-exact; re-synthesis exists only as the flagged fallback. On the phone channel the
   old hand-rolled bridge that carried those bytes is gone (Pipecat port); byte-exact
   phone audio now comes from Twilio's native full-call recording, with a per-turn Pipecat
   capture left as a follow-up.
2. **No auth, by explicit directive** — consistent with mission.md's single-tenant
   demo posture ("no auth product surface"). **Privacy note recorded**: replay exposes
   caller-provided info (names, zips, emails) to anyone who can reach the app; this is
   acceptable for the take-home (mission non-goal: real PII compliance) and MUST be
   listed in README known limitations. The production path (auth + retention) is
   deliberately out of scope.
3. **jsonb-additive, no migration** — `ts`/`audio_seq` are optional keys on existing
   transcript entries; sessions recorded before this feature replay as text.
4. **Filesystem convention over an audio metadata table** — paths are derivable from
   `session_id` + `audio_seq`, mirroring the uploads-volume pattern; the DB stays
   free of audio bookkeeping.
5. **Recording must not alter conversation behavior** — hooks are write-only
   side-effects on existing code paths; the whole existing test suite staying green is
   the enforcement.

## Architecture impact
- Invariant-preserving: no constitution rule changes; `mission.md` scope gains one
  line (this feature) with the privacy pointer. Adds `app/recordings/` routes, small
  persistence hooks in the two audio paths, and two web pages.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; tool registry untouched
  (no agent-visible surface — this is app/API/UI only).
- Ownership (COORDINATION §3 addition): `app/recordings/`, `web/app/recordings/`. The web
  recording hooks touch `app/ws/routes.py` (voice-diagnostic-core, unchanged). The phone
  recording surface is now Twilio-native (`<Start><Recording>` in `app/phone/twiml.py`,
  retained) plus the deferred per-turn Pipecat capture in `app/voice/`
  (`2026-07-09-pipecat-voice-port/` ownership) — declared as Integration deltas for the
  lead, per COORDINATION §3.
- Constraints: hooks must be best-effort (an audio-write failure never breaks a live
  call — mirror the `_speak` TTS-failure pattern); no auth added anywhere.
- Open question (deferred): serving audio with range requests for scrubbing — start
  with whole-file responses.
