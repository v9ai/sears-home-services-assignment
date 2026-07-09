# Pipecat Integration Hardening — Validation

## Automated
- [ ] `python -m app.voice.verify_tools` — tool parity + guardrails + spoken hygiene all PASS.
- [ ] `tests/voice/` — handshake containment (normal, no-start, malformed, disconnect), serializer
      drops-not-raises on malformed frames, and pipeline-build/metrics smoke test pass.
- [ ] `tests/test_fillers.py` — `CACHED_STRINGS` length assertion passes (4); web-filler imports
      still resolve.
- [ ] `tests/test_tts_cache.py` — cache/passthrough behavior unchanged (still keyed on
      `PHONE_TOOL_FILLER`).
- [ ] `make lint` + `make test` clean.

## Manual
1. Read `app/voice/serializer.py` and confirm the malformed-frame path returns `None` and logs a
   sanitized event (no payload).
2. Read the reconciled docs (`README.md` diagram, `docs/technical-design.md` phone bullet + Models
   table, `docs/local-twilio-run.md` historical banner) and confirm no live reference to the deleted
   `app/phone/{bridge,routes,vad,real_agent}.py` modules remains as if current.
3. Live (via `docs/local-twilio-run.md` cloudflared flow): call `+1 (318) 646-8479`; confirm a
   mid-call glitch no longer drops the call, the `twilio.*` event stream reads as a complete call
   story, and end-of-speech → first-audio stays within the p50 ≤ 2.5 s / p95 ≤ 4 s budget.

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates above are green.
- [ ] Invariant-preserving: no `mission.md` / `tech-stack.md` non-negotiable changed (the STT
      Models-table row already documents the OpenAI `gpt-4o-transcribe` default; Deepgram is
      removed as a provider option throughout code and docs).
- [ ] Deferred scope (`gpt-4.1-mini` promotion, `make eval-live`) recorded as follow-ups.
