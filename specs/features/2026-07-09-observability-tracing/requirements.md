# Observability & Tracing — Requirements

Structured, correlated events across the whole Twilio call path plus full LlamaIndex
agent tracing, so any live-call incident is diagnosable from `wrangler tail` alone —
no reproduction needed. Motivated directly by the 2026-07-09 premature-call-end RCA,
which took hours because the phone path logged sparse lines and the agent was a black
box (the container's stdout wasn't even captured until that fix).

## Decisions

1. **LlamaIndex-native instrumentation, logging-only backend.** Tracing uses
   `llama_index.core.instrumentation` (dispatcher + `BaseEventHandler` +
   `BaseSpanHandler`) — the library's own seam, no third-party APM/OTel dependency
   (take-home scope; the handler boundary makes a future OTel exporter a drop-in).
2. **One line per event, `key=value`, grep-able.** `event=<dotted.name>` first, then
   correlation ids, then fields. No JSON logger dependency; `wrangler tail | grep
   event=twilio.` must be a complete call story.
3. **Correlation via contextvars, not parameter threading.** `session_id` /
   `call_sid` / `turn_index` bind once per call/turn (`app/obs.py`); every event —
   including ones emitted deep inside llama-index — carries them automatically.
4. **Logging must never affect the call.** Handlers are exception-proof; the deep
   dump (`TRACE_DUMP_DIR`) is off by default and best-effort.

## Event catalog (contract)

| Event | Required fields |
|---|---|
| `twilio.webhook` | call_sid, from_last4, signature_valid, ms |
| `twilio.stream.start` | call_sid, stream_sid, session |
| `twilio.turn.closed` | speech_ms, turn_index |
| `twilio.stt` | ms, chars, turn_index |
| `twilio.turn.processed` | ms, ok, turn_index |
| `twilio.bargein` | turn_index |
| `twilio.call.summary` | turns, frames_in, barge_ins, duration_s, eos_first_audio_p50_ms, eos_first_audio_p95_ms |
| `twilio.rest.<op>` | ms, ok (every Twilio REST call) |
| `llama.llm.start` | model, n_messages, input_chars |
| `llama.llm.ttft` | ms |
| `llama.llm.end` | ms, output_chars (+ prompt_tokens/completion_tokens when available) |
| `llama.tool.call` | tool, arg_keys |
| `llama.embedding` | ms, n_texts |
| `llama.exception` | error_type |
| `llama.span` | span, ms (agent/llm/tool span exits) |
| `turn_trace` (existing, extended) | + llm_calls, tool_calls, tool_names, output_chars |

## Scope
- In: `app/obs.py`, `app/agent/instrumentation.py`, wiring in phone routes/bridge/
  webhook/twilio_client/real_agent + web ws route trace completeness, tests.
- Out: metrics backends, dashboards, sampling, OTel export (future spec).

## Gates
- Full suite green; instrumentation adds zero behavior change to audio paths.
- A scripted fake call's log output contains the complete event chain
  (stream.start → per-turn stt/turn.processed → call.summary) with consistent ids.
- run_turn's own ToolCall handling emits llama.tool.call (with the fake LLM too —
  the reliable, always-firing signal; llama.llm.start/end fire for real providers,
  see instrumentation.py's module docstring for why the test fake can't trigger them).
