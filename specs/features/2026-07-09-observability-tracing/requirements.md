# Observability & Tracing — Requirements

Structured, correlated events across the phone channel — the `POST /twilio/voice`
webhook (`app/phone/webhook.py`) and the Pipecat voice pipeline (`app/voice`, see
`2026-07-09-pipecat-voice-port`) — plus full LlamaIndex agent tracing, so any live-call
incident is diagnosable from `wrangler tail` alone — no reproduction needed. Motivated
directly by the 2026-07-09 premature-call-end RCA, which took hours because the phone
path logged sparse lines and the agent was a black box (the container's stdout wasn't
even captured until that fix). The hand-rolled media bridge/routes/real_agent this spec
originally instrumented (`app/phone/{routes,bridge,real_agent}.py`) were later **deleted**
in the Pipecat port; per-call media timing now comes from Pipecat's own metrics
(`PipelineParams(enable_metrics=…, enable_usage_metrics=…)`) plus the pipeline's `voice_*`
log lines, not the bespoke `twilio.*` turn events (see § Event catalog).

## Decisions

1. **LlamaIndex-native instrumentation, logging-only backend.** Tracing uses
   `llama_index.core.instrumentation` (dispatcher + `BaseEventHandler` +
   `BaseSpanHandler`) — the library's own seam, no third-party APM/OTel dependency
   (take-home scope; the handler boundary makes a future OTel exporter a drop-in).
2. **One line per event, `key=value`, grep-able.** `event=<dotted.name>` first, then
   correlation ids, then fields. No JSON logger dependency. The retained webhook/REST
   path keeps the structured `event=twilio.*` lines; the Pipecat pipeline emits its own
   `voice_*` `logger.info` lines (`app/voice`) plus Pipecat's built-in metrics, so a call
   story is now assembled from `event=twilio.webhook` → `voice_*` → `event=llama.*` (all
   sharing the `call=` id bound in `app/voice/routes.py`), not from a single
   `grep event=twilio.`.
3. **Correlation via contextvars, not parameter threading.** `session_id` /
   `call_sid` / `turn_index` bind once per call/turn (`app/obs.py`); every event —
   including ones emitted deep inside llama-index — carries them automatically.
4. **Logging must never affect the call.** Handlers are exception-proof; the deep
   dump (`TRACE_DUMP_DIR`) is off by default and best-effort.

## Event catalog (contract)

### Retained structured events (`event=<name>`, correlation ids attached automatically)

| Event | Source | Required fields |
|---|---|---|
| `twilio.webhook` | `app/phone/webhook.py` (retained) | call, signature_valid, ms |
| `twilio.rest.<op>` | `app/recordings/routes.py` (retained; e.g. `twilio.rest.recordings_list`) | ms, ok |
| `llama.llm.start` | `app/agent/instrumentation.py` | model, n_messages, input_chars |
| `llama.llm.ttft` | `app/agent/instrumentation.py` | ms |
| `llama.llm.end` | `app/agent/instrumentation.py` | ms, output_chars (+ prompt_tokens/completion_tokens when available) |
| `llama.tool.call` | `app/agent/core.py` (`ToolCall` handling) | tool, arg_keys |
| `llama.embedding` | `app/agent/instrumentation.py` | ms, n_texts |
| `llama.exception` | `app/agent/instrumentation.py` | error_type |
| `llama.span` | `app/agent/instrumentation.py` | span, ms (agent/llm/tool span exits) |
| `turn_trace` (existing, extended) | `app/agent` | + llm_calls, tool_calls, tool_names, output_chars |

### Phone media-path signals (Pipecat pipeline, `app/voice`)

These are plain `logger.info` lines carrying the `call=`/`session=` ids (bound in
`app/voice/routes.py`), **not** the `event=` structured format — the Pipecat frame
processors and bot own them (see `2026-07-09-pipecat-voice-port`):

| Log line | Source | Fields |
|---|---|---|
| `twilio_ws_start` | `app/voice/routes.py` | stream, call |
| `voice_call_connected` | `app/voice/bot.py` (`on_client_connected`) | call, session |
| `voice_call_ended` | `app/voice/bot.py` (`on_client_disconnected`) | call, session |
| `voice_safety_interrupt` | `app/voice/processors.py` (`SafetyGateProcessor`) | category, call |
| `voice_tool_failed` | `app/voice/tools.py` (tool-handler resilience) | tool, args |

Per-call/per-turn media timing + model usage come from Pipecat's built-in metrics,
enabled by `PipelineParams(enable_metrics=True, enable_usage_metrics=True)` in
`app/voice/bot.py` (processing/TTFB latency per service + LLM/TTS token/character usage),
emitted by the framework rather than by our `log_event`.

### Historical (pre-Pipecat-port)

The following `twilio.*` turn events were emitted by the hand-rolled media loop in
`app/phone/{routes,bridge,real_agent}.py`, which was **deleted** in
`2026-07-09-pipecat-voice-port`; their emit points no longer exist and their signal is
now covered by the Pipecat metrics + `voice_*` lines above:

| Retired event | Was emitted from | Now covered by |
|---|---|---|
| `twilio.stream.start` (call_sid, stream_sid, session) | `app/phone/routes.py` | `twilio_ws_start` + `voice_call_connected` |
| `twilio.turn.closed` (speech_ms, turn_index) | `app/phone/bridge.py` (RMS VAD) | Silero `VADProcessor` turn segmentation + Pipecat metrics |
| `twilio.stt` (ms, chars, turn_index) | `app/phone/real_agent.py` | Pipecat STT service metrics |
| `twilio.turn.processed` (ms, ok, turn_index) | `app/phone/real_agent.py` | Pipecat pipeline processing metrics |
| `twilio.bargein` (turn_index) | `app/phone/bridge.py` | Pipecat native interruptions/barge-in |
| `twilio.call.summary` (turns, frames_in, barge_ins, duration_s, eos_first_audio_p50/p95_ms) | `app/phone/routes.py` | Pipecat aggregate metrics, bracketed by `voice_call_connected`/`voice_call_ended` |

## Scope
- In: `app/obs.py`, `app/agent/instrumentation.py` (both **unchanged** — LlamaIndex still
  owns tools/prompts/tracing); the retained `app/phone/webhook.py` +
  `app/recordings/routes.py` REST timing; the Pipecat pipeline `voice_*` lines +
  `PipelineParams` metrics (`app/voice`, per `2026-07-09-pipecat-voice-port`); web ws
  route trace completeness; tests. The deleted `app/phone/{routes,bridge,real_agent}.py`
  wiring is historical.
- Out: metrics backends, dashboards, sampling, OTel export (future spec).

## Gates
- Full suite green; instrumentation adds zero behavior change to audio paths.
- A `tests/voice` pipeline run's log output shows the correlated phone-path chain
  (`twilio.webhook` → `twilio_ws_start`/`voice_call_connected` → `voice_*` → per-turn
  `llama.*`/`turn_trace` → `voice_call_ended`) with consistent `call=` ids; the old
  hand-rolled `stream.start → stt/turn.processed → call.summary` chain was retired with
  `app/phone/{routes,bridge,real_agent}.py`.
- run_turn's own ToolCall handling emits llama.tool.call (with the fake LLM too —
  the reliable, always-firing signal; llama.llm.start/end fire for real providers,
  see instrumentation.py's module docstring for why the test fake can't trigger them).
