# Voice Diagnostic Core (Tier 1) — Plan

Implement in dependency order. Run the relevant gate after each group; pause for review
after groups 4 and 5.

## 1. Scaffold
- [x] `pyproject.toml` (FastAPI, uvicorn, llama-index-core, llama-index-llms-openai,
      SQLAlchemy 2 async, asyncpg, alembic, openai, pydantic, pyyaml, ruff, pytest,
      pytest-asyncio, deepeval). — landed in the Phase 0b foundation commit (6d0dcda).
- [x] App layout `app/{main,ws,agent,tools,knowledge,db}`, `/healthz`, `Makefile`,
      `.env.example`. — package skeletons from Phase 0b; `dev`/`web-dev`/`migrate`
      Makefile bodies filled in by this feature.
- [x] Base `docker-compose.yml`: `db` (postgres:18-alpine, `pg_isready` healthcheck,
      `pgdata` volume) + `app` (Dockerfile build, port 8000) + `web` (Next.js, port
      3000, `NEXT_PUBLIC_*` pointing at `app`). — landed in Phase 0b.

## 2. DB plane
- [x] SQLAlchemy async engine/session setup; Alembic init. (`app/db/base.py`)
- [x] Rev 001: `customers`, `sessions` per requirements contract shapes; `make migrate`.
      (`app/db/models_core.py`, `alembic/versions/0001_core_initial.py`; verified against
      a live Postgres 18 container — schema matches the contract exactly.)

## 3. Knowledge
- [x] Author six `app/knowledge/<appliance>.yaml` files — ≥3 symptom trees each, one
      safety-escalation tree per file (e.g. oven gas smell, washer water-near-electrics).
- [x] Loader + schema validation, unit-tested. (`app/knowledge/{schema,loader}.py`,
      `tests/test_knowledge.py`)

## 4. Agent core                                       ⏸ review after this group
- [x] Four tools: `identify_appliance`, `record_symptom`, `get_troubleshooting_steps`,
      `update_case_file`. (`app/tools/core_tools.py`)
- [x] System prompt: persona, safety interrupt, never-re-ask contract, case-file
      injection each turn; `ChatMemoryBuffer` per session. (`app/agent/prompts.py`,
      `app/agent/core.py` rebuilds the prompt fresh every turn.)
- [x] Text-only harness (no TTS) proving the conversation loop against a scripted caller.
      (`tests/fakes.py` + `tests/test_agent_core.py` drive the real `AgentWorkflow` +
      `FunctionAgent` + tool-calling loop end to end against a scripted
      `FakeFunctionCallingLLM`, no live OpenAI key needed.)

## 5. Voice pipeline + WS bridge                       ⏸ review after this group
- [x] Sentence-chunker over agent token stream; `gpt-4o-mini-tts` streaming client.
      (`app/agent/pipeline.py`, `app/agent/tts.py`)
- [x] `/ws/call` endpoint wiring: user_text in → transcript/audio/state frames out.
      (`app/ws/routes.py`, mounted in `app/main.py`)
- [x] Latency instrumentation logs (first-token, first-audio). (`app/agent/core.py`
      logs `first_token_latency_ms`; `app/ws/routes.py` logs `first_audio_latency_ms`.)

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
