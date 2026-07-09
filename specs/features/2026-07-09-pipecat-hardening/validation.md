# Pipecat Integration Hardening — Validation

## Automated
- [x] `python -m app.voice.verify_tools` — tool parity + guardrails + spoken hygiene all PASS
      (run 2026-07-09: "ALL CHECKS PASSED").
- [x] `tests/voice/` — handshake containment (normal, no-start, malformed, disconnect), serializer
      drops-not-raises on malformed frames, and pipeline-build/metrics smoke test pass
      (2026-07-09: 70 passed, incl. the new `test_llm_factory.py` provider/model-selection suite).
- [x] `tests/test_fillers.py` — `CACHED_STRINGS` length assertion passes (4); web-filler imports
      still resolve.
- [x] `tests/test_tts_cache.py` — cache/passthrough behavior unchanged (still keyed on
      `PHONE_TOOL_FILLER`).
- [x] `make lint` + `make test` clean (2026-07-09: lint green after `ruff format` on three files
      from commit `29f3552`; full suite 367 passed).

## Manual
1. [x] Read `app/voice/serializer.py` and confirm the malformed-frame path returns `None` and logs a
   sanitized event (no payload). — Verified 2026-07-09: `SafeTwilioFrameSerializer.deserialize`
   catches `KeyError`/`ValueError`, logs `voice.malformed_twilio_frame` with the exception *type
   name* only, returns `None`.
2. [x] Read the reconciled docs (`README.md` diagram, `docs/technical-design.md` phone bullet + Models
   table, `docs/local-twilio-run.md` historical banner) and confirm no live reference to the deleted
   `app/phone/{bridge,routes,vad,real_agent}.py` modules remains as if current. — Verified
   2026-07-09: all remaining references sit under the "Historical (pre-Pipecat port)" banner in
   `local-twilio-run.md` or are explicitly framed as "replaces/removed by the port"
   (`app/voice/routes.py` docstring, `app/phone/stt.py` docstring). README diagram + design-doc
   Models table were re-reconciled the same day to the `29f3552` defaults (Deepgram STT, Cartesia
   TTS, `LLM_PROVIDER=openai`).
3. [ ] Live (via `docs/local-twilio-run.md` cloudflared flow): call `+1 (318) 646-8479`; confirm a
   mid-call glitch no longer drops the call, the `twilio.*` event stream reads as a complete call
   story, and end-of-speech → first-audio stays within the phone e2e budget
   (`specs/latency/budgets.md`).
   — **Owed**: requires a real handset; the number's `voiceUrl` currently points at the quick
   tunnel (verified live via the Twilio API 2026-07-09, `/healthz` 200).

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true.
- [x] All automated gates above are green.
- [x] Invariant-preserving: no `mission.md` / `tech-stack.md` non-negotiable changed. *Note*: this
      bullet's original parenthetical ("Deepgram is removed as a provider option throughout code
      and docs") described the interim `777189d` state and was superseded the same day by
      `29f3552`, which **reinstated** Deepgram STT + Cartesia TTS as defaults; the Models table
      rows now document that reinstated state.
- [x] Deferred scope (`gpt-4.1-mini` promotion, `make eval-live`) recorded as follow-ups
      (testing-evals plan group 7; roadmap Phase 1b note).
