# Observability & Tracing — Validation

## Automated
- [x] `log_event` format unit (ordering, escaping, bound-context attach).
- [x] Instrumentation registration idempotent (double-register → one handler set).
- [x] Fake-LLM `run_turn` → caplog contains `event=llama.llm.start`,
      `event=llama.llm.end`, `event=llama.tool.call` with `session=` bound.
- [x] Scripted fake call → `event=twilio.stream.start`, per-turn `event=twilio.stt`
      + `event=twilio.turn.processed`, closing `event=twilio.call.summary` with
      turns/frames counts matching the script; barge-in emits `event=twilio.bargein`.
- [x] Handler exception-proofing: a raising handler never breaks a turn.
- [x] Full suite green (329 passed, lint clean).

## Manual
1. `wrangler tail` during one real call: complete correlated chain webhook →
   stream.start → stt/llm/tool/turn_trace per turn → call.summary.
2. `TRACE_DUMP_DIR=data/traces` locally: per-session JSONL appears and replays.
