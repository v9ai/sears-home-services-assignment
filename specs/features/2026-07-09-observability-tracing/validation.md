# Observability & Tracing — Validation

## Automated
- [x] `log_event` format unit (ordering, escaping, bound-context attach).
- [x] Instrumentation registration idempotent (double-register → one handler set).
- [x] Fake-LLM `run_turn` → caplog contains `event=llama.llm.start`,
      `event=llama.llm.end`, `event=llama.tool.call` with `session=` bound.
- [x] `tests/voice/` exercises the Pipecat pipeline offline (assembly, `/ws/twilio`
      route, tool/guardrail/schema parity); the phone media path's timing/usage now comes
      from Pipecat's `enable_metrics`/`enable_usage_metrics` and its `voice_*` lines
      (`voice_call_connected`/`voice_safety_interrupt`/`voice_call_ended`), not the retired
      `event=twilio.stream.start/stt/turn.processed/call.summary/bargein` chain. The scripted
      `tests/phone/test_call_events.py` that asserted that chain was removed with the
      hand-rolled loop (see `2026-07-09-pipecat-voice-port`).
- [x] Handler exception-proofing: a raising handler never breaks a turn.
- [x] Full suite green (329 passed, lint clean).

## Manual
1. `wrangler tail` during one real call: complete correlated chain `event=twilio.webhook`
   → `twilio_ws_start`/`voice_call_connected` → per-turn `event=llama.*`/`turn_trace` +
   Pipecat metrics → `voice_call_ended` (all sharing the `call=` id).
2. `TRACE_DUMP_DIR=data/traces` locally: per-session JSONL appears and replays.
