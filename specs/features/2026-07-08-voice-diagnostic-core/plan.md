# Voice Diagnostic Core (Tier 1) — Plan

Implement in dependency order. Run the relevant gate after each group; pause for review
after groups 4 and 5.

## 1. Scaffold
- [ ] `pyproject.toml` (FastAPI, uvicorn, llama-index-core, llama-index-llms-openai,
      SQLAlchemy 2 async, asyncpg, alembic, openai, pydantic, ruff, pytest).
- [ ] App layout `app/{main,ws,agent,tools,knowledge,db}`, `/healthz`, `Makefile`,
      `.env.example`.
- [ ] Base `docker-compose.yml`: `db` (postgres:18-alpine, `pg_isready` healthcheck,
      `pgdata` volume) + `app` (Dockerfile build, port 8000) + `web` (Next.js, port
      3000, `NEXT_PUBLIC_*` pointing at `app`).

## 2. DB plane
- [ ] SQLAlchemy async engine/session setup; Alembic init.
- [ ] Rev 001: `customers`, `sessions` per requirements contract shapes; `make migrate`.

## 3. Knowledge
- [ ] Author six `app/knowledge/<appliance>.yaml` files — ≥3 symptom trees each, one
      safety-escalation tree per file (e.g. oven gas smell, washer water-near-electrics).
- [ ] Loader + schema validation, unit-tested.

## 4. Agent core                                       ⏸ review after this group
- [ ] Four tools: `identify_appliance`, `record_symptom`, `get_troubleshooting_steps`,
      `update_case_file`.
- [ ] System prompt: persona, safety interrupt, never-re-ask contract, case-file
      injection each turn; `ChatMemoryBuffer` per session.
- [ ] Text-only harness (no TTS) proving the conversation loop against a scripted caller.

## 5. Voice pipeline + WS bridge                       ⏸ review after this group
- [ ] Sentence-chunker over agent token stream; `gpt-4o-mini-tts` streaming client.
- [ ] `/ws/call` endpoint wiring: user_text in → transcript/audio/state frames out.
- [ ] Latency instrumentation logs (first-token, first-audio).

## 6. Chat page
- [ ] Scaffold `web/` (Next.js App Router, TypeScript) with the chat page: input box,
      transcript panel, sequential audio playback queue, case-file state panel; WS
      client to `/ws/call`; `web/.env.example`.
- [ ] Document the two `NEXT_PUBLIC_*` env vars in `web/.env.example` (hosted deploy
      itself lands in Phase 4 on Cloudflare Containers).

## 7. Gates
- [ ] pytest: knowledge loader, case-file merge, tool units (fake LLM), safety interrupt.
- [ ] `make transcript`: scripted golden-path conversation (see validation).
- [ ] `make eval`: DeepEval suite in `evals/` — ConversationalTestCase per transcript
      scenario; Knowledge Retention, Role Adherence, Conversation Completeness, G-Eval
      safety rubric; thresholds pinned, judge `gpt-4o`.
- [ ] `make lint` clean; `docker compose up` smoke (`/healthz` 200).
- [ ] Tick roadmap Phase 1 `[x]` in `specs/constitution/roadmap.md`.
