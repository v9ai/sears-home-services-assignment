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

## 3. Phone-path wiring
- [x] webhook + signature check → `twilio.webhook` (`app/phone/webhook.py`, retained).
- [x] Pipecat pipeline media-path signals (`app/voice`, per
      `2026-07-09-pipecat-voice-port`): `twilio_ws_start` (`routes.py`),
      `voice_call_connected`/`voice_call_ended` (`bot.py`), `voice_safety_interrupt`
      (`processors.py`), `voice_tool_failed` (`tools.py`); per-call media timing + model
      usage via `PipelineParams(enable_metrics=True, enable_usage_metrics=True)`.
      **Supersedes** the deleted hand-rolled `app/phone/{routes,bridge,real_agent}.py`
      emitters of `stream.start / turn.closed / stt / turn.processed / bargein /
      call.summary` (those files were removed in the port).
- [x] REST call timing (`twilio.rest.recordings_list` in `app/recordings/routes.py`,
      where the actual `client.recordings.list()` calls happen — `twilio_client.py`
      itself only constructs the client, it makes no REST calls of its own).
- [x] Trace completeness: `log_turn_trace` per turn on the web channel;
      `bind_call_context(call_sid=…)` in `app/voice/routes.py` correlates the phone
      pipeline's `voice_*` lines to the same call id.

## 4. Tests
- [x] `tests/test_obs.py` + `tests/test_instrumentation.py` (registration idempotent;
      fake-LLM turn emits llm/tool events with session id).
- [x] `tests/voice/` covers the Pipecat pipeline (assembly, `/ws/twilio` route,
      guardrail/schema parity). The old `tests/phone/test_call_events.py` (scripted-call
      chain + summary counts + barge-in event) was removed with the hand-rolled media loop
      it drove; the retired `twilio.*` turn events it asserted no longer exist.

## 5. Gates
- [x] Full suite + lint; constitution updates (COORDINATION row, tech-stack note).
- [ ] Announced deploy + `wrangler tail` verification on a real call (manual, owed).
