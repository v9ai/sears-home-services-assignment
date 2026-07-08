# Call Recording & In-App Replay — Plan

Additive feature; implement in dependency order. Recording hooks are best-effort and
must never affect a live call.

## 1. Recording layer
- [ ] `app/calls/recorder.py`: `save_turn_audio(session_id, seq, data, fmt) -> None`
      (best-effort, logged failures) + path convention helpers; `RECORDINGS_DIR` env.
- [ ] Transcript entries gain `ts` (+ `audio_seq` when audio saved) at the two append
      sites — web `_speak`/user-turn append, phone `RealAgent._say`/`handle_turn` and
      the STT caller-utterance path (caller wav). *(Shared files — apply as lead or
      declare per COORDINATION §3.)*

## 2. Calls API
- [ ] `app/calls/routes.py`: `GET /api/calls` (newest first, limit/offset),
      `GET /api/calls/{id}`, `GET /api/calls/{id}/audio/{seq}` (content-type by ext,
      404 on miss). Read-only; mounted in `app/main.py` (integration delta).

## 3. Replay UI                                        ⏸ review after this group
- [ ] `web/app/calls/page.tsx`: list with channel badge, date, appliance, duration.
- [ ] `web/app/calls/[id]/page.tsx`: transcript bubbles, play-all via
      `web/lib/audioQueue.ts`, per-turn play, `ts`-gap pacing for text-only turns,
      final `CaseFilePanel`.
- [ ] Nav link from the chat page.

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
- `app/main.py`: mount `calls_router`.
- `app/ws/routes.py` + `app/phone/{real_agent,routes}.py`: the recording hook calls
  (owned by voice-diagnostic-core / telephony respectively).
- `docker-compose.yml`: `recordings` volume; `.env.example` additions.
- README known-limitations: open no-auth replay privacy note (requirements Decision 2).
