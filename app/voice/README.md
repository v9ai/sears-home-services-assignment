# Voice pipeline (Pipecat + Twilio) — `app/voice`

This package is the **Pipecat port of the phone channel**. It replaces the old hand-rolled
Twilio media bridge (`app/phone/*`: µ-law codec, RMS VAD, batch STT, custom TTS queueing)
with a Pipecat pipeline — **transport → STT → LLM → TTS** — while **reusing every piece of
LlamaIndex business logic unchanged** (tools, prompts, guardrails, knowledge base).

LlamaIndex still owns retrieval/RAG and all business logic; Pipecat owns the real-time
voice pipeline. The bridge between them is `app/voice/tools.py`, which re-exposes each
LlamaIndex tool as a Pipecat function-calling tool.

```
 caller ─▶ Twilio ─▶ POST /twilio/voice ─(TwiML <Connect><Stream>)─▶ wss://…/ws/twilio
                                                                        │
   transport.input ─ VAD(Silero) ─ STT(OpenAI) ─ SafetyGate ─ PromptRefresh
        ─ context.user ─ LLM(OpenAI gpt-4o + ported tools) ─ Sanitizer ─ TTS(OpenAI)
        ─ transport.output ─ context.assistant
```

---

## Step 1 — Inventory of the existing LlamaIndex code (what we reused)

- **RAG store (one index):** `appliance_library` collection — **embedded Qdrant** +
  **local FastEmbed `BAAI/bge-small-en-v1.5`**, **retrieval-only** (`similarity_top_k=3`,
  no reranker/filters/query-engine), built by `scripts/ingest_library.py`. Reached only
  through the `search_appliance_library` tool, **flag-gated OFF** (`LIBRARY_RAG_ENABLED`).
  Source: `app/knowledge/library_store.py`.
- **Primary knowledge:** a deterministic YAML lookup (six appliances, `app/knowledge/*.yaml`)
  via `get_troubleshooting_steps` — **not** the vector index.
- **Agent:** a single LlamaIndex `FunctionAgent` in an `AgentWorkflow`, rebuilt each turn
  (`app/agent/core.py`), default LLM DeepSeek `deepseek-chat` (OpenAI `gpt-4o` fallback).
- **Tools** (`app/tools/*`, auto-discovered): `identify_appliance`, `record_symptom`,
  `get_troubleshooting_steps`, `update_case_file`, `find_technicians`, `book_appointment`,
  `send_image_upload_link`, `check_image_analysis`, and the flag-gated `search_appliance_library`.
  They read the live `CaseFile` / session id via **ContextVars** (`app/agent/state.py`).
- **Prompts** (`app/agent/prompts.py`): `build_system_prompt(case_file)` = PERSONA (already
  voice-tuned) + NON_NEGOTIABLES + SCHEDULING/IMAGE contracts + knowledge vocab + the
  **compact `CaseFile` JSON** (the never-re-ask mechanism) + a safety-flag suffix. `GREETING`
  is the spoken opener.
- **Guardrails** (`app/agent/safety.py`): a deterministic **pre-LLM** regex
  (`detect_safety_trigger`, 5 hazard categories) → speak fixed `SAFETY_RESPONSE`, never
  enter the agent loop.
- **Memory:** LlamaIndex `ChatMemoryBuffer` (verbatim history) + the structured `CaseFile`
  (facts re-injected into the prompt each turn). Session state in `app/agent/session_store.py`.

## Step 2 — How each concept maps to Pipecat

| LlamaIndex | Pipecat (this package) |
|---|---|
| `FunctionAgent` tool-calling loop | The **Pipecat LLM service** runs the loop directly (`bot.py`). |
| each `FunctionTool` | a `FunctionSchema` + handler in `tools.py` that calls the **same** `app.tools.*` fn inside `session.bind()` (ContextVars) — no logic rewritten. |
| retriever / `search_appliance_library` | a Pipecat function tool calling the same `library_store.retrieve` (flag-gated). |
| `as_chat_engine` | n/a — this repo is all function-calling, so we keep the tool pattern. |
| `build_system_prompt(case_file)` | carried verbatim; re-injected into the LLM context each turn by `SystemPromptRefreshProcessor`. |
| agent/workflow routing | the set of function tools the LLM chooses between (same single-agent, prompt-driven branching; no Pipecat Flows needed). |
| `detect_safety_trigger` (pre-LLM) | `SafetyGateProcessor` after STT — swallows the transcription and speaks `SAFETY_RESPONSE`. |
| `ChatMemoryBuffer` + `CaseFile` | Pipecat context aggregator (verbatim history) + `VoiceSession.case_file` (structured, refreshed into the prompt). |
| voice output hygiene | `SpokenTextSanitizer` strips markdown/URLs before TTS. |

**Not ported 1:1 / notes**
- "Rebuild the agent each turn" → "refresh the system message each turn" (same effect).
- `book_appointment` used to file `session_id=NULL`; the port runs tools inside
  `session.bind()`, so bookings are attributable to the call (gap closed).
- The library RAG tool needs the Qdrant index built (`scripts/ingest_library.py`); it stays
  **off by default**, exactly as before.
- Cross-call Postgres session persistence (`session_store`) is **not** wired on the live turn
  path (Pipecat owns per-call memory); it can be added fire-and-forget if durable history is wanted.

## Files

| File | Role |
|---|---|
| `bot.py` | `run_bot()` — builds the transport, STT/LLM/TTS (swappable), context + aggregators, registers the ported tools, assembles the pipeline + task. |
| `tools.py` | Ported tools: `FunctionSchema` + handlers bridging to `app.tools.*`. |
| `processors.py` | `SafetyGateProcessor`, `SystemPromptRefreshProcessor`, `SpokenTextSanitizer`. |
| `session.py` | `VoiceSession` (per-call `CaseFile` + session id) and the ContextVar `bind()`. |
| `text.py` | `sanitize_for_speech` (pure, unit-testable). |
| `routes.py` | `@websocket("/ws/twilio")` — reads Twilio's `start`, calls `run_bot`. |
| `verify_tools.py` | Offline verification (tool parity, guardrails, sanitizer). |

The webhook (`POST /twilio/voice`), TwiML, and signature validation stay in `app/phone/`
(`webhook.py`, `twiml.py`, `signature.py`) — unchanged.

---

## Run it locally

```bash
pip install -r requirements.txt            # or: pip install -e .
cp .env.example .env                        # fill in the keys below

# minimum for a live call:
#   OPENAI_API_KEY     (STT gpt-4o-transcribe + LLM gpt-4o + TTS gpt-4o-mini-tts)
#   TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN   (signature validation + auto-hangup)
#   PUBLIC_HOST        (your public tunnel host, set after the tunnel is up)

# start the FastAPI app (serves /twilio/voice + /ws/twilio):
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Expose it with a tunnel

Twilio must reach your machine over HTTPS/WSS:

```bash
ngrok http 8000            # or: cloudflared tunnel --url http://localhost:8000
```

Set `PUBLIC_HOST` in `.env` to the tunnel host (bare host, no scheme — e.g.
`abc123.ngrok.app`) and restart uvicorn. The TwiML builder turns this into
`wss://$PUBLIC_HOST/ws/twilio`.

### Point the Twilio number at it

In the Twilio console → your number → **Voice → A call comes in**:

- Set **Webhook** to `https://$PUBLIC_HOST/twilio/voice`, method **HTTP POST**.

(Signature validation uses `TWILIO_AUTH_TOKEN`; `PUBLIC_HOST` must match the URL Twilio
signs.)

### Place a test call

Call the number. You should hear the greeting, then a streaming, barge-in-capable
conversation: describe an appliance problem, get troubleshooting steps, and ask to book a
technician. Say something hazardous ("I smell gas") to trigger the safety interrupt.

## Swapping providers

All via env (`.env.example` documents each):

- `LLM_PROVIDER=openai|deepseek` (+ `VOICE_LLM_MODEL`, default `gpt-4o`)
- `TTS_PROVIDER=openai|cartesia` (Cartesia for lowest latency — add the matching key)

## Verify without a phone call

```bash
python -m app.voice.verify_tools     # tool parity, guardrails fire, spoken hygiene
pytest tests/voice/                  # the same checks as pytest
```

- **Tool parity:** each ported handler returns exactly what the original `app.tools.*`
  function returns for sample questions.
- **Guardrails:** the safety gate speaks `SAFETY_RESPONSE`, sets `safety_flag`, and swallows
  the transcription so the LLM never runs on a hazard.
- **Responsiveness / clean speech (live):** the pipeline streams LLM tokens to TTS and
  handles barge-in (Silero VAD + interruptions); `SpokenTextSanitizer` strips markdown/URLs.
