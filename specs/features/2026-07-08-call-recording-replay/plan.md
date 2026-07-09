# Call Recording & In-App Replay — Plan

Additive feature; implement in dependency order. Recording hooks are best-effort and
must never affect a live call.

> **As-built note (2026-07-09).** The phone channel was re-architected to the Pipecat
> pipeline after this plan was written: `app/phone/{real_agent,routes}.py` no longer
> exist, and phone recording became a single full-call stereo WAV
> (`app/voice/recording.py`, caller-left/bot-right, wired in `app/voice/bot.py`)
> instead of per-utterance files. The web channel records per-turn WAV (not mp3)
> inline in `app/ws/routes.py` (`_write_recording`/`_record_async`) rather than via a
> shared `app/recordings/recorder.py` — the shared-module refactor was dropped as the
> two channels' shapes diverged. Items below are ticked against that shipped design.

## 1. Recording layer
- [x] Best-effort audio persistence + path convention + `RECORDINGS_DIR` env — as-built:
      web per-turn writes in `app/ws/routes.py:_write_recording`/`_record_async`
      (`{RECORDINGS_DIR}/{session_id}/{seq:05d}.wav`, failures swallowed + logged);
      phone full-call WAV path helpers in `app/voice/recording.py:call_recording_path`.
      *(The planned shared `app/recordings/recorder.py::save_turn_audio` was superseded
      — see as-built note.)*
- [x] Transcript entries gain `ts` (+ `audio_seq` when audio saved) at the web append
      sites (`app/ws/routes.py` `_speak`/user-turn/tool entries). Phone transcripts are
      derived post-call via `app/voice/recording.py:transcript_from_context` against the
      single full-call WAV (no per-turn `audio_seq` by design).

## 2. Recordings API
- [x] `app/recordings/routes.py`: `GET /api/recordings` (newest first, limit/offset),
      `GET /api/recordings/{id}`, `GET /api/recordings/{id}/audio/{seq}` (content-type by ext,
      404 on miss) — plus as-built extras `/call-audio` (full-call WAV) and
      `/twilio-audio/{sid}` (dual-channel Twilio recording proxy). Read-only; mounted in
      `app/main.py`.

## 3. Dedicated Recordings page
- [x] `web/app/recordings/page.tsx`: the dedicated all-recordings list — channel
      badge, date+time, appliance, duration, turn count, inline quick-play per row,
      limit/offset pagination.
- [x] `web/app/recordings/[id]/page.tsx`: transcript bubbles, play-all via
      `web/lib/audioQueue.ts`, per-turn play, `ts`-gap pacing for text-only turns,
      final `CaseFilePanel`.
- [x] Persistent "Recordings" nav link — as-built via the shared `web/components/nav-bar.tsx`
      mounted in `web/app/layout.tsx` (appears on the chat page header and everywhere else).

## 4. Plumbing
- [x] Compose: `recordings` named volume on `app` (`docker-compose.yml`); `.env.example`:
      `RECORDINGS_DIR`, `REPLAY_TTS_FALLBACK`, `VOICE_RECORDING_ENABLED`.
- [x] Optional `REPLAY_TTS_FALLBACK` re-synthesis path (off by default;
      `app/recordings/routes.py:_tts_fallback_enabled` → `_resynthesize_audio`).

## 5. Gates
- [x] pytest: API list/get/audio (ordering, 404s, bytes + content-type) in
      `tests/test_recordings_routes.py`; recorder best-effort + backward-compat +
      scripted-WS-turn writes in `tests/test_ws_recording_hooks.py`; phone full-call
      recorder units in `tests/voice/test_call_recording.py`.
- [x] Full suite green unchanged — recording must not alter agent behavior
      (requirements Decision 5; write failures swallowed on both channels, enforced by
      `test_speak_write_failure_is_swallowed` / scripted-turn equivalents).
- [x] `make lint` + `make transcript` clean.
- [ ] Tick roadmap Phase 7 `[x]` when green — **owed**: roadmap keeps Phase 7 unticked
      pending the manual browser replay check (validation.md Manual item 1).

## Integration deltas (lead applies)
- `app/main.py`: mount `recordings_router`. ✅
- `app/ws/routes.py` recording hook calls ✅; the planned `app/phone/{real_agent,routes}.py`
  hooks were superseded by the Pipecat full-call recorder (`app/voice/bot.py`).
- `docker-compose.yml`: `recordings` volume; `.env.example` additions. ✅
- README known-limitations: open no-auth replay privacy note (requirements Decision 2). ✅
