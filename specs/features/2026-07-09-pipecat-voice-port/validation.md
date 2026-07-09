# Pipecat Voice Pipeline Port — Validation

## Automated (the gates this surface triggers)
- [x] `make test` clean — includes `tests/voice/`:
  - **Tool parity** — each ported Pipecat handler returns byte-identical output to its
    `app/tools/*` origin for sample inputs (`test_voice_port.py`, `verify_tools.py`).
  - **Guardrail parity** — the `SafetyGateProcessor` (using the same `detect_safety_trigger`)
    fires on exactly the scenarios whose `assert.safety_interrupt` is true, across the whole
    matrix (`test_voice_guardrail_parity.py`); on a hazard it swallows the transcription (LLM
    never runs) and speaks `SAFETY_RESPONSE`.
  - **Schema parity** — `build_tools()` `FunctionSchema`s expose the frozen tool params
    (`test_voice_schema_parity.py`), with voice `book_appointment = {slot_id, issue_summary}`.
  - **Pipeline assembly + provider selection** — `build_pipeline_task` builds with a fake
    transport; `_build_stt/_build_llm/_build_tts` pick Deepgram / OpenAI gpt-4o /
    gpt-4o-mini-tts by default and swap on env (`test_voice_bot.py`).
  - **WS route** — `/ws/twilio` reads `connected`/`start` and calls `run_bot` with the parsed
    `stream_sid`/`call_sid` (`test_voice_routes.py`).
  - **Bridge edge cases** — customer assembled from the case file; tool-failure → spoken-safe
    string; ContextVars bound during the call and reset after (`test_voice_tools_extra.py`).
- [x] `make lint` (`ruff check` + `ruff format --check`) clean.
- [x] `python -m app.voice.verify_tools` prints ALL CHECKS PASSED (parity / guardrails / hygiene).
- [ ] `make eval-voice` — DeepEval over the voice channel's **spoken** output (each transcript
  through `voice_lens`), same metrics/thresholds/judge as `make eval` + structural assertions.
  SKIP-with-warning without a judge key; **needs `DEEPSEEK_API_KEY`** (or `OPENAI_API_KEY` when
  `EVAL_JUDGE_PROVIDER=openai`) to score.

## Manual
1. Read a driven transcript / recording: the agent speaks in short sentences, no markdown or
   URLs read aloud; the greeting plays immediately on answer.
2. **Live-call checklist** (carried from `2026-07-08-telephony-twilio/validation.md`, needs
   `DEEPGRAM_API_KEY` + `OPENAI_API_KEY` + `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` +
   `PUBLIC_HOST`): expose the app via a tunnel, point the Twilio number's Voice webhook at
   `https://{PUBLIC_HOST}/twilio/voice`, place a real call, and confirm: greeting → appliance
   ID → symptom capture → troubleshooting → scheduling; **barge-in** interrupts the agent;
   **safety interrupt** fires on "I smell gas" and halts DIY; never-re-ask holds across turns;
   streaming-to-TTS stays responsive within the p50 ≤ 2.5 s / p95 ≤ 4 s envelope.
3. Spot-check that `app/phone/{webhook,twiml,signature}` still validate `X-Twilio-Signature`
   and emit the `<Connect><Stream>` TwiML unchanged (`tests/phone/` green).

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true in `app/voice`.
- [x] All automated gates above are green (`make test`/`make lint`/`verify_tools`); `make
      eval-voice` runs and SKIPs cleanly without a key, scores with one.
- [x] Constitution updated in the same change (`tech-stack.md`/`mission.md`/`roadmap.md`/
      `COORDINATION.md`) — this feature is constitution-revising (non-negotiable 6).
- [x] Deferred scope (cross-call persistence, µ-law audio evals, web-mic STT) recorded in the
      roadmap Enhancement backlog.
- [x] Roadmap Phase 10 ticked `[x]` (automated gates); the live-call/PDF-readiness manual gate
      is credential-blocked and tracked, matching the Phase 5 posture.
