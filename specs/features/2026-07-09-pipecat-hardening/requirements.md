# Pipecat Integration Hardening — Requirements

## Source
Pasted requirement (not from the roadmap):
> check specs and find where Pipecat integration might fall

A spec-gap analysis of the shipped Pipecat phone path (`app/voice/`, landed in commit
`8169740`) against the binding specs — mission non-negotiables (`specs/constitution/mission.md`),
telephony + latency requirements (`specs/features/2026-07-08-telephony-twilio/`,
`.../2026-07-08-latency-engineering/`), and `specs/constitution/tech-stack.md` — surfaced five
risk areas. The Pipecat port deleted the hand-rolled `app/phone/{bridge,routes,vad,real_agent}.py`
media bridge **and its resilience tests**, reintroducing a call-drop crash class (commit
`70f32c2`) and leaving stale docs.

## Scope

### Included
- **A1 — Handshake containment** (`app/voice/routes.py`): the `/ws/twilio` start-frame read loop
  survives a malformed/binary frame (skip it) and an abrupt disconnect (close cleanly); no
  exception escapes. Structured events for each degraded path.
- **A2 — Pipeline teardown guard** (`app/voice/bot.py::run_bot`): `runner.run(task)` wrapped so any
  unexpected error logs a sanitized event and cancels the task (belt-and-braces beyond
  `on_client_disconnected`).
- **A3 — Media-frame resilience** (`app/voice/serializer.py`): a `SafeTwilioFrameSerializer`
  subclass wraps `deserialize()` so one malformed Media Streams frame is dropped, not raised —
  Pipecat's transport wraps its whole receive loop in a single `try/except`, so an unguarded raise
  ends the call. Restores the `70f32c2` guarantee at a boundary we own + test.
- **B1 — Twilio-credential observability** (`app/voice/bot.py::run_bot`): missing
  `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` emits a structured `autohangup_disabled` event instead
  of failing opaquely.
- **B2 — Voice-LLM latency note** (`app/voice/bot.py::_build_llm`): inline documentation of the
  `gpt-4o` (default) vs. `gpt-4.1-mini` (tuned latency winner) tradeoff against the first-audio
  budget. Default unchanged (deliberate quality choice; env-overridable via `VOICE_LLM_MODEL`).
- **C — Test coverage** (`tests/voice/`): handshake containment, serializer resilience, and a
  pipeline-build/metrics smoke test — the Pipecat-era replacement for the deleted
  `test_malformed_media_frame_does_not_end_the_call` / `tests/phone/test_routes.py`.
- **D1 — Doc rot**: stale references to deleted modules fixed in `docs/local-twilio-run.md`,
  `docs/twilio-webhook-setup.md`, and the `app/phone/stt.py` docstring.
- **D2 — Dead code** (`app/agent/fillers.py`): remove the importer-less `PHONE_TURN_FAILED_FALLBACK`
  (and drop it from `CACHED_STRINGS`); retain `PHONE_TOOL_FILLER` with a documenting comment.
- **E — Architecture reconciliation**: `README.md`, `docs/technical-design.md`, and the
  `tech-stack.md` Models table describe the shipped Pipecat + Deepgram streaming STT path, not the
  deleted custom bridge / `gpt-4o-transcribe`-as-default.

### Not included (deferred)
- Changing the `VOICE_LLM_MODEL` default to `gpt-4.1-mini` — flagged only, per user directive.
- A live end-to-end phone regression harness (`make eval-live`) — separate roadmap item.

### Contract shapes
- Source-of-truth file(s): `app/voice/routes.py`, `app/voice/bot.py`, `app/voice/serializer.py`,
  `app/agent/fillers.py`; docs `README.md`, `docs/technical-design.md`, `docs/local-twilio-run.md`,
  `docs/twilio-webhook-setup.md`; `specs/constitution/tech-stack.md` (Models table).
- Structured events (privacy-safe, `app/obs.log_event`): `twilio.ws.disconnected_during_handshake`,
  `voice.malformed_handshake_frame`, `twilio.ws.no_start_event`, `twilio.stream.start`,
  `voice.malformed_twilio_frame`, `twilio.serializer.autohangup_disabled`, `twilio.pipeline.error`.
- Gate path: `make test` (`tests/voice`, `tests/phone`, `tests/test_fillers.py`,
  `tests/test_tts_cache.py`), `make lint`, `python -m app.voice.verify_tools`.

## Decisions
1. **Resilience at the boundary we own** — subclass `TwilioFrameSerializer` rather than patch
   Pipecat, so the drop-don't-crash behavior is unit-testable and survives Pipecat upgrades.
2. **Flag, don't change, the voice LLM default** — keep `gpt-4o`; document the latency tradeoff
   (user directive 2026-07-09).
3. **Deploy path**: no deploy — code + docs + tests only.
4. **Gate path**: `make test` + `make lint` + `python -m app.voice.verify_tools`.

## Architecture impact
- Component / plane touched: the Pipecat phone channel (`app/voice/`) and its docs; a small
  dead-code removal in shared `app/agent/fillers.py`.
- **Invariant-preserving** — no `mission.md` non-negotiable or `tech-stack.md` forbidden pattern
  changes. The `tech-stack.md` Models-table STT row is a **factual reconciliation** (documenting the
  already-shipped Deepgram default), not a policy revision; the model-provider boundary is untouched
  (Deepgram STT is a permitted non-text modality; the text LLM policy is unchanged).

## Context
- Stack & conventions: `specs/constitution/tech-stack.md` (Pipecat telephony, privacy-safe
  structured logging via `app/obs.py`), `app/voice/README.md` (pipeline shape).
- Constraints: logging must stay privacy-safe (no payloads/secrets — log sanitized exception
  classes only); Twilio remains the sole telephony provider; no new OpenAI text-LLM call.
- Open questions / deferrals: whether to promote `gpt-4.1-mini` as the voice default pending a
  live latency A/B — deferred.
