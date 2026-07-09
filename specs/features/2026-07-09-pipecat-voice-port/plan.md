# Pipecat Voice Pipeline Port — Plan

Implement in dependency order. Run the relevant gate after each group; pause for review
between groups.

## 1. Session + text helpers (no Pipecat dep)                     [foundation]
- [x] `app/voice/session.py` — `VoiceSession{call_sid, case_file, session_id}`;
      `for_call(call_sid)` (stable `uuid5` per CallSid); `bind()` contextmanager setting
      `current_case_file`/`current_session_id` (the same `app/agent/state.py` ContextVars the
      origin tools read) and resetting them after.
- [x] `app/voice/text.py` — `sanitize_for_speech(text)` (strip markdown/`[label](url)`/bare
      URLs/list markers); pure + unit-testable.

## 2. Tool bridge                                                  [ports the tool loop]
- [x] `app/voice/tools.py` — `build_tools(session) -> (ToolsSchema, {name: handler})`:
      one `FunctionSchema` per origin tool (name/description/params mirror the origin
      signature+docstring), handler runs inside `session.bind()` and `await`s the origin
      `app/tools/*` fn, `result_callback`s the string; exceptions → spoken-safe error.
      `book_appointment` assembles `Customer` from the case file (`{slot_id, issue_summary}`).
      RAG tool registered iff `library_tools._flag_enabled()` — mirrors `registry.get_tools()`.
- [x] Inline comment on each tool linking to its `app/tools/<file>.py` origin.

## 3. Processors                                                   [guardrails + memory]
- [x] `app/voice/processors.py` — `SafetyGateProcessor` (pre-LLM `detect_safety_trigger`;
      swallow transcription, speak `SAFETY_RESPONSE`, set `safety_flag`, append both sides to
      context); `SystemPromptRefreshProcessor` (`build_system_prompt(case_file)` into the
      context system message each user turn); `SpokenTextSanitizer` (scrub `TextFrame`/
      `TTSSpeakFrame` via `sanitize_for_speech`).

## 4. Pipeline + Twilio WS route                                  [pipeline change]
- [x] `app/voice/bot.py` — swappable `_build_stt/_build_llm/_build_tts` (env-driven, lazy
      per-provider import); `build_pipeline_task(transport, session)` builds `LLMContext`(+tools)
      + `LLMContextAggregatorPair`, registers handlers, assembles the `Pipeline([...])` in the
      order above, `PipelineTask(PipelineParams(audio_in/out_sample_rate=8000, metrics))`,
      greeting on `on_client_connected` (fixed `GREETING` via `TTSSpeakFrame`), `task.cancel()`
      on disconnect. `run_bot(websocket, stream_sid, call_sid)` builds the serializer + transport
      + `PipelineRunner`.
- [x] `app/voice/routes.py` — `@websocket("/ws/twilio")`: read `connected`/`start`, parse
      `streamSid`/`callSid`, call `run_bot`.
- [x] `app/phone/__init__.py` — repoint `phone_router` at `app.voice.routes` (webhook retained).

## 5. Remove superseded plumbing + deps                            [cleanup]
- [x] Delete `app/phone/{codec,vad,bridge,routes,real_agent,fake_agent,call_context}.py` +
      their tests; keep `stt.py`/`latency.py`/`twilio_client.py`/`signature.py`/`twiml.py`/
      `webhook.py` (still used by the web channel + recordings). Fix `scripts/latency_bench.py`
      (drop the deleted-bridge import).
- [x] `pyproject.toml` + `requirements.txt` — `pipecat-ai[deepgram,openai,silero,websocket]`;
      `.env.example` — new provider keys; `app/voice/README.md` — run/tunnel/test-call.

## 6. Tests + evals                                               [gates]
- [x] `tests/voice/` — `test_voice_port.py` (tool parity, safety gate, prompt refresh,
      sanitizer, session id), `test_voice_schema_parity.py` (FunctionSchema vs frozen
      contract), `test_voice_bot.py` (pipeline assembly + provider selection),
      `test_voice_tools_extra.py` (customer-from-case-file, tool-failure path, ContextVar
      bind/reset), `test_voice_routes.py` (`/ws/twilio` start parsing), `test_voice_guardrail_
      parity.py` (gate fires iff scenario expects safety, across the matrix). `app/voice/
      verify_tools.py` standalone offline check.
- [x] `evals/voice_fixture_lens.py` (`voice_lens` — spoken-sanitize agent turns) +
      `evals/test_voice_conversations.py` (DeepEval over lensed transcripts, same
      metrics/thresholds/judge; + structural assertions). `Makefile` `eval-voice` target.

## 7. Gates
- [x] `make test` (incl. `tests/voice`) + `make lint` clean.
- [x] `python -m app.voice.verify_tools` green (tool parity / guardrails / hygiene).
- [ ] `make eval-voice` with a live judge key (DeepEval over spoken output) — credential-blocked.
- [ ] Live-call checklist + PDF voice readiness (carried from telephony) — credential-blocked.

## Integration deltas
- `app/phone/__init__.py` — **APPLIED**: `phone_router` includes `app.voice.routes` instead of
  the deleted `app.phone.routes`; webhook retained.
- `pyproject.toml` / `requirements.txt` / `.env.example` / `README.md` / `Makefile` /
  `scripts/latency_bench.py` / `docs/technical-design.md` — **APPLIED** (Pipecat deps, new env
  keys, voice README section, `eval-voice`, dropped-bridge import, design-doc Pipecat note).
- Constitution edits (`tech-stack.md`, `mission.md`, `roadmap.md`, `COORDINATION.md`) —
  **APPLIED** in the same change (constitution-revising, non-negotiable 6).
