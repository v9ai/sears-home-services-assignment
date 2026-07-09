# Call Recording & In-App Replay — Plan

Additive feature; implement in dependency order. Recording hooks are best-effort and
must never affect a live call.

## 1. Recording layer
- [ ] `app/recordings/recorder.py`: `save_turn_audio(session_id, seq, data, fmt) -> None`
      (best-effort, logged failures) + path convention helpers; `RECORDINGS_DIR` env.
- [ ] Transcript entries gain `ts` (+ `audio_seq` when audio saved) at the web append
      site — `_speak`/user-turn append (`app/ws/routes.py`, unchanged). The old phone
      append hooks (`RealAgent._say`/`handle_turn`, the STT caller-wav path) are
      **superseded** — those modules were deleted by the Pipecat port
      (`2026-07-09-pipecat-voice-port/`); phone full-call audio is captured natively by
      Twilio (`<Start><Recording>` in `app/phone/twiml.py`, retained), and a per-turn
      Pipecat audio capture in `app/voice/` is a follow-up. *(Shared files — apply as
      lead or declare per COORDINATION §3.)*

## 2. Recordings API
- [ ] `app/recordings/routes.py`: `GET /api/recordings` (newest first, limit/offset),
      `GET /api/recordings/{id}`, `GET /api/recordings/{id}/audio/{seq}` (content-type by ext,
      404 on miss). Read-only; mounted in `app/main.py` (integration delta).

## 3. Dedicated Recordings page                        ⏸ review after this group
- [ ] `web/app/recordings/page.tsx`: the dedicated all-recordings list — channel
      badge, date+time, appliance, duration, turn count, inline quick-play per row,
      limit/offset pagination.
- [ ] `web/app/recordings/[id]/page.tsx`: transcript bubbles, play-all via
      `web/lib/audioQueue.ts`, per-turn play, `ts`-gap pacing for text-only turns,
      final `CaseFilePanel`.
- [ ] Persistent "Recordings" nav link in the chat page header.

## 4. Plumbing
- [ ] Compose: `recordings` named volume on `app`; `.env.example`: `RECORDINGS_DIR`,
      `REPLAY_TTS_FALLBACK` (integration deltas — shared files).
- [ ] Optional `REPLAY_TTS_FALLBACK` re-synthesis path (off by default).

## 5. Gates
- [ ] pytest: API list/get/audio (ordering, 404s, bytes + content-type); recorder unit
      (best-effort on write failure); backward-compat (pre-feature transcript without
      `ts` serves and replays); recording hook writes files for a scripted WS turn.
- [ ] Full suite green unchanged — recording must not alter agent behavior
      (requirements Decision 5).
- [ ] `make lint` + `make transcript` clean.
- [ ] Tick roadmap Phase 7 `[x]` when green.

## Integration deltas (lead applies)
- `app/main.py`: mount `recordings_router`.
- `app/ws/routes.py`: the web recording hook calls (owned by voice-diagnostic-core,
  unchanged). Phone recording is Twilio-native via `app/phone/twiml.py` (retained) — the
  deleted `app/phone/{real_agent,routes}.py` hooks are superseded by the Pipecat port; a
  per-turn Pipecat capture in `app/voice/` is a deferred follow-up.
- `docker-compose.yml`: `recordings` volume; `.env.example` additions.
- README known-limitations: open no-auth replay privacy note (requirements Decision 2).
