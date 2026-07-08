# Observability & Tracing — Plan

## 1. Event core
- [x] `app/obs.py`: `log_event(logger, event, **fields)` + `bind_call_context()` /
      `bound_context()` contextvar; unit-tested formatting + binding.

## 2. LlamaIndex tracing
- [x] `app/agent/instrumentation.py`: `LogEventHandler` (llm start/ttft/end,
      embedding, exception), `LogSpanHandler` (span exits with duration),
      `register_instrumentation()` idempotent; startup hook in `app/main.py`.
      **Tool-call logging moved to `app/agent/core.py`'s own `ToolCall` handling**:
      the installed llama-index-core's `AgentWorkflow` never dispatches
      `AgentToolCallEvent` (confirmed dead in this version) — the workflow event
      `run_turn` already consumes is the only signal that actually fires.
- [x] Per-turn rollup counters folded into `turn_trace` (trace.py extras).
- [x] `TRACE_DUMP_DIR` JSONL deep dump (default off).

## 3. Twilio-path wiring
- [x] webhook + signature check → `twilio.webhook`.
- [x] routes.py: stream.start / turn.closed / stt / turn.processed / bargein /
      **call.summary** (counters kept on the handler; summary on stop AND disconnect).
- [x] REST call timing (`twilio.rest.recordings_list` in `app/recordings/routes.py`,
      where the actual `client.recordings.list()` calls happen — `twilio_client.py`
      itself only constructs the client, it makes no REST calls of its own).
- [x] Trace completeness: `first_audio` + `turn_done` marks both channels;
      `log_turn_trace` per turn on web too.

## 4. Tests
- [x] `tests/test_obs.py` + `tests/test_instrumentation.py` (registration idempotent;
      fake-LLM turn emits llm/tool events with session id).
- [x] `tests/phone/test_call_events.py`: scripted call → full chain + summary counts;
      barge-in event.

## 5. Gates
- [x] Full suite + lint; constitution updates (COORDINATION row, tech-stack note).
- [ ] Announced deploy + `wrangler tail` verification on a real call (manual, owed).
