# Technical Design — Sears Home Services Voice AI Agent

*1–2 page distillation for reviewers. The specs under `specs/features/` remain the
source of truth; this document never contradicts them, only summarizes.*

## Architecture

A single FastAPI backend (`app/`) fronts a **LlamaIndex `FunctionAgent`** running under
`AgentWorkflow`. Two transports feed the same agent through one abstraction,
`SessionBridge` (`receive_user_utterance` / `emit_transcript` / `emit_audio`):

- **Web** (`/ws/call`): a Next.js chat page sends typed text; the backend streams back
  transcript events and `gpt-4o-mini-tts` audio chunks, split at sentence boundaries so
  audio starts before the full reply finishes generating. This is the permanent debug
  harness, not a throwaway prototype.
- **Phone** (`/ws/twilio`, Phase 5): Twilio Media Streams carries base64 μ-law 8 kHz
  audio into a **Pipecat** pipeline (`app/voice`): Silero VAD → Deepgram streaming STT
  (default; OpenAI `gpt-4o-transcribe` via `STT_PROVIDER=openai`) → the LLM running the same
  function-calling tools → `gpt-4o-mini-tts`, re-encoded to
  μ-law. The tools, prompts, guardrails, and case-file memory are reused unchanged (each
  LlamaIndex tool is re-exposed as a Pipecat function-calling tool); only the real-time
  transport differs. (The original hand-rolled `app/phone/` codec/VAD bridge was replaced
  by this Pipecat port — commit `8169740`.)

The agent's tools are auto-discovered (`app/tools/registry.py` walks `app/tools/*.py`
for a module-level `TOOLS` list) so each tier's tools ship as an independent file with
no shared-registry edits: `core_tools.py` (identify appliance, record symptom, fetch
troubleshooting steps), `scheduling_tools.py` (find technicians, book appointment),
`visual_tools.py` (send upload link, check image analysis).

**Memory** is two-layered: a `ChatMemoryBuffer` for conversational flow, plus a
structured pydantic **case file** persisted as `sessions.case_file` jsonb and re-injected
into the system prompt every turn. This makes "never re-ask" (mission non-negotiable 2)
a structural property of the context window, not a prompt-engineering hope.

**Diagnostic knowledge** is deterministic, keyed YAML decision trees
(`app/knowledge/<appliance>.yaml`) — no vector DB, no RAG. Six appliances × a handful of
common symptoms is small enough to be fully authored, auditable, and demo-reliable; a
vector store buys nothing here and adds a failure mode reviewers can't inspect. RAG over
full manufacturer manuals is recorded as a roadmap enhancement once the curated set
outgrows itself.

## Data model (Postgres 18, SQLAlchemy 2 async, Alembic)

```
customers ──< sessions >── technicians ──< technician_specialties >── specialties
                │                │
                │                └──< service_areas (zip_code)
                │                └──< availability_slots >── appointments >── sessions
                └──< image_uploads
```

- `sessions(id, customer_id?, channel ∈ {web,phone}, appliance_type?, case_file jsonb,
  transcript jsonb, started_at, ended_at)` — one row per conversation, either channel.
- `technicians` / `specialties` / `technician_specialties` (junction, not a CSV column —
  keeps the specialty domain extensible) / `service_areas` (zip-indexed) /
  `availability_slots` (pre-generated rows over a two-week horizon, not recurrence rules
  — simpler queries, honest for a demo horizon) / `appointments` (one per claimed slot).
- `image_uploads(token UNIQUE, status, vision_analysis jsonb, expires_at)` — tokenized,
  single-use, 24 h expiry.

**Booking integrity** (mission non-negotiable 4): `book_appointment` claims a slot with
`UPDATE availability_slots SET status='booked' WHERE id=:id AND status='open' RETURNING
id` inside the same transaction as the `appointments` insert. Zero rows back means the
slot was already taken — the tool returns `slot_taken`, the agent apologizes and
re-offers. Double-booking is impossible by construction, not by convention. The agent
also refuses to call this tool until it has read back technician + date + time and
received an explicit "yes."

## Models (server-side only)

| Role | Model | Why |
|---|---|---|
| LLM (agent) | DeepSeek `deepseek-chat` | Function calling + latency for real-time conversation, direct `api.deepseek.com`; `LLM_PROVIDER=openai` falls back to `gpt-4o` |
| TTS | `gpt-4o-mini-tts` | Streamed, steerable "warm service agent" voice |
| Vision | `gpt-4o` (chat-with-image) | The assignment's "GPT-4 Vision" option — `gpt-4-vision-preview` is retired; `gpt-4o` is its current surface |
| STT (phone only) | **Deepgram** streaming (Pipecat default) | Low-latency streaming (finalizes at end-of-speech) fits the phone budget; `STT_PROVIDER=openai` swaps to `gpt-4o-transcribe` (strong on error codes/model numbers), `whisper-1` via `OPENAI_STT_MODEL` |

## Latency budgets

| Path | Budget |
|---|---|
| Web: first text token | < 1.0 s |
| Web: first audio chunk | p50 < 2.0 s, p95 < 3.5 s |
| Phone: end-of-caller-speech → first audio | p50 ≤ 2.5 s, p95 ≤ 4 s (STT 400–900 ms + first agent sentence 600–1500 ms + first TTS chunk 300–500 ms) |

Turn-based pipelines were chosen over OpenAI's Realtime API specifically to keep these
budgets debuggable: Realtime bypasses LlamaIndex tool orchestration and hides the
STT→agent→TTS seams this doc describes. Revisit only if a budget above fails in
practice (`tech-stack.md`).

## Key tradeoffs and sequencing

1. **Text-harness-first, not phone-first.** Tier 1 ships on text + TTS playback before
   the Twilio adapter exists, derisking agent correctness/memory/tools before layering
   on audio-codec and VAD complexity. Phone (Phase 5) is additive: same agent and
   tools, a new `SessionBridge` implementation.
2. **Adapter, not rewrite, for telephony.** The phone channel is a Pipecat pipeline that
   re-runs the function-calling loop over the **same** bridged tools, prompts, guardrails,
   and case-file memory — the business logic (tools/prompts/safety/knowledge) is reused
   verbatim, not forked, so only the real-time driver and transport are telephony-specific.
3. **Deterministic knowledge over RAG.** Chosen for auditability and cost at the
   current appliance/symptom scale; a decision to revisit, not an oversight, once the
   knowledge base outgrows human-authorable YAML.
4. **Migrate + seed in the app entrypoint, not a one-shot service.** Fewer moving parts
   for a fresh-clone reviewer; idempotency in both Alembic and the seed script makes
   re-runs safe.
5. **Cloudflare Containers + Neon for hosting, Compose for local.** Same Dockerfiles
   build both; Workers terminate WebSockets, serving `/ws/call` and the Twilio bridge
   without ngrok. Tradeoff: hosted container disk is ephemeral, so Tier 3 uploads
   aren't durable in production — an accepted, documented limitation for the demo.
   Object storage (including R2) was explicitly rejected (2026-07-08 directive); the
   local Docker named volume (`uploads_data`) is the recorded storage decision.
6. **Parallel development via a frozen-contract foundation commit.** Six feature
   triplets built concurrently against `app/contracts.py` and an ownership map
   (`COORDINATION.md`) instead of sequentially — coordination overhead up front for
   parallel throughput across the 7-day window.

## Honest sequencing of deferred work

Recorded explicitly, not silently dropped (`roadmap.md` → Enhancement backlog /
Non-goals): browser-mic STT, RAG over full service manuals, reschedule/cancel flows,
reminder emails, MMS ingestion, outbound calls/SMS/transfer-to-human, full-duplex
speech, phone-channel audio evals, load/perf testing, CI/CD. (Durable object storage /
R2 is not on this list — it was explicitly rejected, not deferred; see above.)
None block the Tier 1–3 + live-phone-number deliverables; each is a scoped next step.
