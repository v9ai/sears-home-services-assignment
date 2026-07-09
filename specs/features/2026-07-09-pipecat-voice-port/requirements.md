# Pipecat Voice Pipeline Port (Phone Channel) — Requirements

## Source
Roadmap Phase 10 (specs/constitution/roadmap.md). Supersedes Phase 5
`2026-07-08-telephony-twilio/` Decisions 1–3 and its § Contract shapes (the hand-rolled
media bridge). Pasted user directive:
> Port our LlamaIndex customer-support agent logic into a Pipecat voice pipeline (Twilio).
> LlamaIndex KEEPS owning retrieval/RAG; Pipecat owns the voice pipeline (transport → STT →
> LLM → TTS). Expose all our LlamaIndex logic as Pipecat function-calling tools / context,
> then wire it into a working Pipecat + Twilio agent. Do NOT rewrite retrieval or re-invent
> RAG. Preserve ALL business logic: system prompts, guardrails/validation, tool definitions,
> routing/branching, conversational-memory behavior.

## Scope

### Included
- New `app/voice` package = the Pipecat phone pipeline, replacing the deleted `app/phone`
  media loop (`codec.py`, `vad.py`, `bridge.py`, `routes.py`, `real_agent.py`,
  `fake_agent.py`, `call_context.py`).
- Transport: Twilio Media Streams over WebSocket via Pipecat's **`TwilioFrameSerializer`** +
  **`FastAPIWebsocketTransport`**; the `POST /twilio/voice` webhook (`app/phone/webhook.py`)
  + TwiML `<Connect><Stream url="wss://{PUBLIC_HOST}/ws/twilio">` + `X-Twilio-Signature`
  validation are **retained unchanged**; `/ws/twilio` (`app/voice/routes.py`) reads Twilio's
  `connected`/`start` messages then hands the socket to `run_bot`.
- Pipeline order: `transport.input()` → Silero `VADProcessor` → STT → `SafetyGateProcessor`
  → `SystemPromptRefreshProcessor` → user context aggregator → LLM (ported tools) →
  `SpokenTextSanitizer` → TTS → `transport.output()` → assistant context aggregator.
- Providers, swappable via env (keys from env): **STT = Deepgram** (default) / OpenAI;
  **LLM = OpenAI `gpt-4o`** (default, `VOICE_LLM_MODEL`) / DeepSeek; **TTS = OpenAI
  `gpt-4o-mini-tts`** (default) / Cartesia / Deepgram Aura-2. VAD = **Silero**; interruptions/
  barge-in on; 8 kHz end-to-end (Twilio µ-law) so the serializer handles resampling.
- Every LlamaIndex `FunctionTool` (`app/tools/*`) re-exposed as a Pipecat `FunctionSchema` +
  async handler that calls the **same** origin function inside `session.bind()` (the existing
  `current_case_file`/`current_session_id` ContextVars) — **no business logic reimplemented**.
  Same tool set as `registry.get_tools()`, including the flag-gated `search_appliance_library`
  RAG tool (Qdrant retrieval, `LIBRARY_RAG_ENABLED`, default off — unchanged).
- Guardrails: the pre-LLM `detect_safety_trigger` hazard interrupt runs as
  `SafetyGateProcessor` after STT — swallows the transcription (LLM never sees it) and speaks
  the fixed `SAFETY_RESPONSE`; `safety_flag` propagates into the prompt exactly as before.
- System prompt: `build_system_prompt(case_file)` carried verbatim, re-injected each user turn
  (never-re-ask). Voice output hygiene: `SpokenTextSanitizer` strips markdown/URLs before TTS.
- Memory: Pipecat context aggregator (verbatim history) + the case-file-in-prompt refresh
  (structured never-re-ask). `book_appointment` runs inside the call session, closing the old
  `session_id=NULL` gap.
- Tests (`tests/voice`, offline) + a voice DeepEval gate (`make eval-voice`); README, extended
  `.env.example`, `requirements.txt`, `pyproject.toml` Pipecat deps.

### Not included (deferred)
- Cross-call Postgres session persistence on the live phone turn path — Pipecat owns per-call
  memory; wiring `session_store` fire-and-forget is a follow-up (backlog).
- Phone-channel audio-level evals (word-error rate over µ-law audio) — needs a live provider run.
- Replacing the web channel (`/ws/call`, `app/ws/routes.py`) — untouched; still runs the
  LlamaIndex agent directly.
- Full-duplex speech beyond Pipecat's built-in barge-in.

### Contract shapes
- Data/artifact shapes: no change to `app/contracts.py` (`CaseFile`/`Symptom`/`Customer`,
  tool signatures) — the port reuses them. The Pipecat `FunctionSchema` params mirror the
  frozen tool contract (`tests/test_tool_schemas.py:EXPECTED_TOOL_PARAMS`), with the one
  sanctioned difference that voice `book_appointment` = `{slot_id, issue_summary}` (customer
  assembled from the live case file, not an LLM arg).
- Source-of-truth files: `app/voice/*`; retained `app/phone/{webhook,twiml,signature,twilio_client}.py`.
- New env vars: `DEEPGRAM_API_KEY` (secret), `STT_PROVIDER`, `TTS_PROVIDER`, `VOICE_LLM_MODEL`,
  `OPENAI_TTS_VOICE`, `CARTESIA_API_KEY`/`CARTESIA_VOICE_ID` (optional). See `.env.example` +
  `tech-stack.md` § Secrets.
- Pipeline/build targets: `make test` (`tests/voice`), `make eval-voice`, `make lint`.

## Decisions
1. **Pipecat pipeline over the hand-rolled bridge** — replaces `SessionBridge`/codec/RMS-VAD/
   batch-STT/TTS-queue with a maintained framework that gives native barge-in, streaming, and
   swappable services; keeps the STT→LLM→TTS seams visible (not the OpenAI Realtime API).
2. **Twilio serializer + FastAPI WebSocket transport** — Twilio stays the sole PSTN carrier;
   `webhook.py`/`twiml.py`/`signature.py`/`twilio_client.py` retained, so the provisioned
   number keeps working after re-pointing its webhook at `/twilio/voice`.
3. **Silero VAD** (replaces the RMS `TurnSegmenter`) — a Pipeline `VADProcessor`; new
   dependency, revises the old "no new VAD dependency" note.
4. **Deepgram STT** (replaces batch `gpt-4o-transcribe`) — streaming, low-latency;
   `STT_PROVIDER=openai` swaps back. Revises the Models STT row + the "Telephony = Twilio only"
   forbidden pattern (Deepgram is a *media*, not PSTN, provider).
5. **OpenAI `gpt-4o-mini-tts`** retained as TTS; `TTS_PROVIDER` swaps to Cartesia (lowest
   latency) or Deepgram Aura-2 (pronunciation of order numbers/names).
6. **Voice-pipeline LLM = OpenAI `gpt-4o`** (`VOICE_LLM_MODEL`) — reliable real-time
   tool-calling; `LLM_PROVIDER=deepseek` swaps in `deepseek-chat` for parity. Reconciled via
   the dated **Model-provider boundary amendment** (`tech-stack.md`): a sanctioned, confined
   exception; the web agent LLM and DeepEval judge stay on DeepSeek.
7. **LlamaIndex retains tools/prompts/guardrails/knowledge** — each tool re-exposed as a
   Pipecat function tool that calls the origin unchanged; `detect_safety_trigger` and
   `build_system_prompt` reused verbatim; RAG unchanged and flag-gated.
8. **Deploy path**: `make up` (Compose) / hosted WSS — no new deploy path; the Pipecat app runs
   in the same FastAPI container.
9. **Gate path**: `make test` (`tests/voice` — tool/guardrail/schema parity, pipeline assembly,
   provider selection, `/ws/twilio` route) + `make eval-voice` (DeepEval over spoken output) +
   `make lint`; plus the manual live-call checklist carried from telephony `validation.md`.

## Architecture impact
- Component/plane: the **phone transport layer** (`app/phone` media loop → `app/voice` Pipecat).
  The agent/tool/knowledge plane (`app/agent`, `app/tools`, `app/knowledge`) and the web channel
  (`app/ws`) are unchanged.
- **Constitution-revising** (updated in the same change per mission non-negotiable 6):
  - `tech-stack.md`: Runtime telephony; Agent-framework voice-pipeline note; Models table (STT →
    Deepgram, phone LLM row, TTS swappable); Model-provider boundary **amendment** (voice LLM on
    OpenAI); Forbidden patterns ("Telephony (PSTN) = Twilio only" clarified; "No OpenAI Realtime"
    rationale); Make commands (`eval-voice`); Evaluation (voice gate); Observability (Pipecat
    traces); Env classification (`DEEPGRAM_API_KEY` etc.).
  - `mission.md`: phone-channel in-scope bullet + scope-out clarification.
  - `roadmap.md`: Phase 5 marked superseded; **Phase 10** added; Phase 8/9 notes.
  - `COORDINATION.md`: `SessionBridge` frozen contract superseded for the phone channel;
    ownership map (retained `app/phone/*` + new `app/voice/` row); integration-order step 5.

## Parallel execution (COORDINATION.md §3–4)
- Owned paths: `app/voice/`, `tests/voice/`, `evals/voice_fixture_lens.py`,
  `evals/test_voice_conversations.py`, the new env keys, `requirements.txt`.
- Integration deltas (shared files, lead-applied): `app/phone/__init__.py` (route repoint),
  `pyproject.toml` (Pipecat deps), `.env.example`, `README.md`, `Makefile` (`eval-voice`),
  `scripts/latency_bench.py` (drop deleted-bridge import), `docs/technical-design.md`.

## Context
- Stack & conventions: `tech-stack.md` (Runtime, Agent framework, Models, Evaluation);
  the ported code reuses `app/tools/*`, `app/agent/{prompts,safety,state}.py`,
  `app/knowledge/*`, `app/contracts.py`.
- Constraints: preserve the safety non-negotiable structurally (pre-LLM gate); preserve
  never-re-ask (case file in prompt every turn); secrets via env only; Twilio = sole PSTN
  carrier; RAG stays flag-gated + never ahead of the safety gate.
- Current Pipecat APIs consulted (Pipecat 1.5.x): `LLMContext` + `LLMContextAggregatorPair`,
  `VADProcessor(vad_analyzer=SileroVADAnalyzer())`, `FunctionSchema`/`ToolsSchema`,
  `llm.register_function`, `FunctionCallParams`, `TwilioFrameSerializer`,
  `FastAPIWebsocketTransport`/`FastAPIWebsocketParams`.
- Open questions / deferrals: cross-call persistence, µ-law audio evals, web-mic STT — backlog.
