# Pipecat Integration Hardening — Plan

Implement in dependency order. Run the relevant gate after each group.

## 1. Resilience & config (pipeline change)
- [x] `app/voice/serializer.py`: add `SafeTwilioFrameSerializer(TwilioFrameSerializer)` overriding
      `deserialize()` to catch `KeyError`/`ValueError` (covers `json.JSONDecodeError`), log
      `voice.malformed_twilio_frame`, and return `None`. Use it in `run_bot`. (A3)
- [x] `app/voice/routes.py`: guard the handshake read loop — `WebSocketDisconnect` → log
      `twilio.ws.disconnected_during_handshake` and return; non-text/JSON errors → log
      `voice.malformed_handshake_frame` and continue; no-`start` → `twilio.ws.no_start_event` +
      clean close; success → `twilio.stream.start`. (A1)
- [x] `app/voice/bot.py::run_bot`: wrap `runner.run(task)` in try/except → log
      `twilio.pipeline.error` (sanitized class only) + `task.cancel()`. (A2) Emit
      `twilio.serializer.autohangup_disabled` when Twilio creds are blank. (B1)
- [x] `app/voice/bot.py::_build_llm`: inline latency-tradeoff comment; default stays `gpt-4o`. (B2)

## 2. Dead code (content change)
- [x] `app/agent/fillers.py`: remove `PHONE_TURN_FAILED_FALLBACK` (no importers) from the module and
      `CACHED_STRINGS`; retain `PHONE_TOOL_FILLER` with a documenting comment. (D2)
- [x] `tests/test_fillers.py`: update the `CACHED_STRINGS` length assertion (5 → 4).

## 3. Docs (content change)
- [x] `docs/local-twilio-run.md`: mark the "Issues hit during first live call" section historical
      (pre-Pipecat bridge); drop the broken `sed app/phone/real_agent.py` verification. (D1)
- [x] `docs/twilio-webhook-setup.md`: repoint the CallSid-correlation note from the deleted
      `app/phone/real_agent.py` to `app/voice/routes.py` + `VoiceSession.for_call`. (D1)
- [x] `app/phone/stt.py`: docstring reflects that `pcm16_to_wav_bytes` serves the web channel and
      `OpenAITranscriber` is pre-Pipecat (VAD via the removed `app.phone.vad`). (D1)
- [x] `README.md`, `docs/technical-design.md`: describe the Pipecat pipeline and its STT/TTS
      providers. *Note*: this item's original wording ("OpenAI `gpt-4o-transcribe` sole/default,
      Deepgram removed") described the interim `777189d` state and was superseded the same day by
      `29f3552`, which reinstated Deepgram STT + Cartesia TTS as defaults (with
      `STT_PROVIDER=openai` as the swap) — the docs were re-reconciled to that shipped state,
      matching validation.md §Definition-of-done. (E)

## 4. Gates
- [x] `python -m app.voice.verify_tools` — offline tool/guardrail parity clean.
- [x] `make test` — `tests/voice`, `tests/phone`, `tests/test_fillers.py`, `tests/test_tts_cache.py`
      green; new handshake/serializer/pipeline tests pass. (C)
- [x] `make lint` clean.
