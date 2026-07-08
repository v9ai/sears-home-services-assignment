# Observability & Tracing — Validation

## Automated
- [ ] `log_event` format unit (ordering, escaping, bound-context attach).
- [ ] Instrumentation registration idempotent (double-register → one handler set).
- [ ] Fake-LLM `run_turn` → caplog contains `event=llama.llm.start`,
      `event=llama.llm.end`, `event=llama.tool.call` with `session=` bound.
- [ ] Scripted fake call → `event=twilio.stream.start`, per-turn `event=twilio.stt`
      + `event=twilio.turn.processed`, closing `event=twilio.call.summary` with
      turns/frames counts matching the script; barge-in emits `event=twilio.bargein`.
- [ ] Handler exception-proofing: a raising handler never breaks a turn.
- [ ] Full suite green (no audio-path behavior change).

## Manual
1. `wrangler tail` during one real call: complete correlated chain webhook →
   stream.start → stt/llm/tool/turn_trace per turn → call.summary.
2. `TRACE_DUMP_DIR=data/traces` locally: per-session JSONL appears and replays.
