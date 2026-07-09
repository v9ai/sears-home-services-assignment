# Voice Diagnostic Core (Tier 1) — Requirements

## Source
Roadmap Phase 1 (specs/constitution/roadmap.md). Assignment Tier 1:
> Inbound call handling · appliance identification (washer, dryer, refrigerator,
> dishwasher, oven, HVAC) · symptom collection (what's happening, when it started, error
> codes, unusual sounds) · diagnostic guidance · conversation memory (never re-ask).

Project directive: build the diagnostic core first on a **text chat + OpenAI TTS
playback** channel (the permanent debug harness); the Twilio phone channel follows in
Phase 5. Focus: LlamaIndex, PostgreSQL, OpenAI TTS.

## Scope

### Included
- FastAPI app skeleton with `/healthz`, plus the **base Docker Compose** (`app` + `db`)
  since the DB is a Phase 1 dependency.
- WS session endpoint `/ws/call`: caller sends text, server streams transcript events and
  TTS audio chunks back.
- Chat page in the **Next.js app (`web/`)**: text input, live transcript panel,
  auto-playing queued TTS audio, case-file state panel; WS client to `/ws/call`. A
  Compose `web` service runs it locally; hosted deploys land on Cloudflare Containers
  in Phase 4.
- LlamaIndex `FunctionAgent` with a service persona prompt that encodes the safety
  interrupt and never-re-ask non-negotiables.
- Appliance identification across the six types; symptom collection (description, onset,
  error codes, sounds) into the case file.
- Troubleshooting-step delivery from curated knowledge, with the safety interrupt.
- Session + case-file persistence (Alembic rev 001).

### Not included (deferred)
- Mic input / STT and PSTN telephony — roadmap Phase 5, the Twilio channel
  (`2026-07-08-telephony-twilio/`).
- Scheduling tools — Phase 2. Image analysis — Phase 3. RAG over manuals — backlog.

### Contract shapes
- WS protocol (byte-identical wherever repeated):
  - client → server: `{"type": "user_text", "text": str}`
  - server → client: `{"type": "transcript", "role": "user"|"agent", "text": str}` ·
    `{"type": "audio", "chunk": b64, "seq": int}` · `{"type": "state", "case_file": {...}}`
- `CaseFile` (pydantic, persisted as `sessions.case_file` jsonb):
  `{appliance_type: "washer"|"dryer"|"refrigerator"|"dishwasher"|"oven"|"hvac"|null,
    brand: str|null, model: str|null,
    symptoms: [{description, onset, error_code|null, sound|null}],
    safety_flag: bool, steps_given: [str],
    customer: {name?: str, zip?: str, email?: str}}`
- Alembic rev 001: `customers(id, name, phone, email, created_at)`;
  `sessions(id uuid PK, customer_id FK null, channel text CHECK IN ('web','phone')
  DEFAULT 'web', appliance_type text null, case_file jsonb DEFAULT '{}',
  transcript jsonb DEFAULT '[]', started_at, ended_at)`.
- Knowledge files: `app/knowledge/<appliance>.yaml`, entries
  `{symptom_key: {questions: [str], steps: [str], escalate_if: str}}` — ≥3 symptom trees
  per appliance, each file including at least one safety-escalation tree.
- Pipeline / build target: `make up` · gates `make lint`, `make test`,
  `make transcript`, `make eval`.

## Decisions
1. **Single `FunctionAgent` + tools, not multi-agent** — tools `identify_appliance`,
   `record_symptom`, `get_troubleshooting_steps(appliance, symptom_key)`,
   `update_case_file`. One agent is debuggable and sufficient at six appliance types;
   `AgentWorkflow` leaves the multi-agent seam open for Phases 2–3 tool groups.
2. **Turn-based text→agent→TTS pipeline, not the Realtime API** — agent token deltas are
   split at sentence boundaries and piped to `gpt-4o-mini-tts` concurrently with
   generation; audio chunks stream back interleaved with transcript events. Budget:
   web tier per `specs/latency/budgets.md` (first token + first audio p50/p95);
   tool-call turns add a spoken filler ("Let me check that…"). Realtime API rejected
   per `tech-stack.md` — it bypasses LlamaIndex tool orchestration.
3. **Diagnostic knowledge = deterministic YAML decision trees, not RAG** — six appliances
   × ~5 common issues is small, auditable, and demo-reliable; keyed tool lookup keeps the
   system prompt lean. RAG-over-manuals stays a roadmap enhancement.
4. **Memory = `ChatMemoryBuffer` per session + case file injected into the system prompt
   every turn** — never-re-ask is enforced structurally: captured facts live outside the
   token window, survive reconnects, and are assertable in tests.
5. **Eval gate = DeepEval over the transcript scenarios** — Knowledge Retention
   (never-re-ask), Role Adherence (persona), Conversation Completeness, and a custom
   G-Eval safety rubric, judged by `gpt-4o` with pinned thresholds in `evals/`
   (see `tech-stack.md` → Evaluation).
6. **Deploy path**: `make up` (base Compose lands here) — the single-command launch is a
   mission non-negotiable. **Gate path**: `make lint` + `make test` + `make transcript`
   + `make eval` + compose smoke.

> **Revision (2026-07-08)**: the agent LLM was switched from `gpt-4o` to DeepSeek
> `deepseek-chat` (direct, LlamaIndex function calling) by
> `specs/features/2026-07-08-deepseek-agent-llm/` — the FunctionAgent/tool decisions
> above are unchanged; `gpt-4o` remains as the `LLM_PROVIDER=openai` fallback, and the
> latency budget in Decision 2 is re-checked in that spec's validation.

## Architecture impact
- Establishes every plane: API, agent, DB, client, Compose. Invariant-preserving — the
  constitution was written for this feature.

## Parallel execution (COORDINATION.md §3–4)
- Owned paths: `app/ws/`, `app/agent/`, `app/tools/core_tools.py`, `app/knowledge/`,
  `app/db/models_core.py`, `alembic/versions/0001_core*`, `web/app/(chat)/`, `web/lib/`.
- Consumes frozen contracts: `CaseFile`, WS frames, tool signatures, rev id
  `0001_core`. This feature is the **critical path** — it builds the real agent all
  other agents stub.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`. Touches `app/{main,ws,agent,
  tools,knowledge,db}`, `web/` (Next.js chat page), `docker-compose.yml`, `Makefile`.
- Constraints: mission non-negotiables 1–3; all `tech-stack.md` forbidden patterns.
- Open question (deferred): whether the spoken filler plays on every tool turn or only
  when the tool round-trip exceeds ~1 s.
