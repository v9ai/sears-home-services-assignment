# Observability & Tracing — Plan

## 1. Event core
- [ ] `app/obs.py`: `log_event(logger, event, **fields)` + `bind_call_context()` /
      `bound_context()` contextvar; unit-tested formatting + binding.

## 2. LlamaIndex tracing
- [ ] `app/agent/instrumentation.py`: `LogEventHandler` (llm start/ttft/end, tool
      call, embedding, exception), `LogSpanHandler` (span exits with duration),
      `register_instrumentation()` idempotent; startup hook in `app/main.py`.
- [ ] Per-turn rollup counters folded into `turn_trace` (trace.py extras).
- [ ] `TRACE_DUMP_DIR` JSONL deep dump (default off).

## 3. Twilio-path wiring
- [ ] webhook + signature check → `twilio.webhook`.
- [ ] routes.py: stream.start / turn.closed / stt / turn.processed / bargein /
      **call.summary** (counters kept on the handler; summary on stop AND disconnect).
- [ ] twilio_client.py REST timing wrapper.
- [ ] Trace completeness: `first_audio` + `turn_done` marks both channels;
      `log_turn_trace` per turn on web too.

## 4. Tests
- [ ] `tests/test_obs.py` + `tests/test_instrumentation.py` (registration idempotent;
      fake-LLM turn emits llm/tool events with session id).
- [ ] `tests/phone/test_call_events.py`: scripted call → full chain + summary counts;
      barge-in event.

## 5. Gates
- [ ] Full suite + lint; constitution updates (COORDINATION row, tech-stack note);
      announced deploy; wrangler tail verification on a real call.
