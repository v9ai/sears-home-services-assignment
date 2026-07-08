# Call Recording & In-App Replay (all calls, no auth) — Requirements

## Source
User directive (2026-07-08):
> need a way to record all calls and be able to replay in the app for all users no auth

Builds on Phase 1's session persistence — `sessions.transcript` jsonb already records
every turn `{role, text}` on **both** channels (web: `app/agent/session_store.py:
persist_session` called from `app/ws/routes.py`; phone: `app/phone/real_agent.py`).
This feature adds per-turn timing + audio capture, a read-only calls API, and a replay
UI.

## Scope

### Included
- **Recording — additive, no migration.** Transcript entries gain optional `ts`
  (ISO-8601) and `audio_seq` (int) keys (jsonb — old sessions stay valid, replay
  text-only). Agent TTS audio is persisted **at synthesis time** (the bytes already
  flow through the app; zero extra API calls) to
  `{RECORDINGS_DIR}/{session_id}/{seq}.{mp3|wav}` — web channel stores the mp3 it
  already synthesizes; phone stores wav from the 24 kHz PCM. Phone **caller**
  utterances persisted as wav at STT time (`app/phone/routes.py:_close_out_turn`
  already holds the PCM). Web caller turns are text-only (typed; no audio exists).
  Recording is **always-on for all channels** — that is the directive.
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

### Not included (deferred)
- Raw full-duplex phone audio (barge-in overlap capture) — per-utterance files are the
  recorded fidelity.
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
1. **Store-at-synthesis over re-synthesize-at-replay** — the audio bytes already pass
   through `_speak` (web) and the phone bridge; persisting them is free and replay is
   byte-exact. Re-synthesis exists only as the flagged fallback.
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
- Ownership (COORDINATION §3 addition): `app/recordings/`, `web/app/recordings/`. The recording
  hooks touch `app/ws/routes.py` (voice-diagnostic-core) and `app/phone/*`
  (telephony) — declared as Integration deltas for the lead, per COORDINATION §3.
- Constraints: hooks must be best-effort (an audio-write failure never breaks a live
  call — mirror the `_speak` TTS-failure pattern); no auth added anywhere.
- Open question (deferred): serving audio with range requests for scrubbing — start
  with whole-file responses.
