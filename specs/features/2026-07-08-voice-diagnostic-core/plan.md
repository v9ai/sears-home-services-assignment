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
- [x] Scaffold `web/` (Next.js App Router, TypeScript) with the chat page: input box,
      transcript panel, sequential audio playback queue, case-file state panel; WS
      client to `/ws/call`; `web/.env.example`. (`web/app/(chat)/page.tsx` +
      `chat.module.css`, `web/lib/{types,session,wsClient,audioQueue}.ts`.) Replaces
      the Phase 0b placeholder `web/app/page.tsx` at the same route (a route group
      doesn't add a URL segment, so the chat page *is* `/`); `next build` and
      `tsc --noEmit` both pass.
- [x] Document the two `NEXT_PUBLIC_*` env vars in `web/.env.example` (hosted deploy
      itself lands in Phase 4 on Cloudflare Containers). — already present from the
      Phase 0b foundation scaffold.

## 7. Gates
- [x] pytest: knowledge loader, case-file merge, tool units (fake LLM), safety interrupt.
      50 tests green (`tests/test_{knowledge,core_tools,safety,pipeline,agent_core}.py`).
- [x] `make transcript`: scripted golden-path conversation (see validation). Landed
      via the testing-evals merge (2026-07-08): the full 24-scenario matrix passes in
      fixture mode, canaries red-as-expected; `--live` mode available pending a real
      `DEEPSEEK_API_KEY`. This feature's own equivalent proof remains
      `tests/test_agent_core.py` (real `AgentWorkflow` loop, scripted LLM).
- [ ] `make eval`: DeepEval suite — harness merged and plumbing verified; judge
      scoring pending a real `OPENAI_API_KEY` (skip-warn today; see roadmap →
      Integration status item 1).
- [x] `make lint` clean (`ruff check` + `ruff format --check`, run directly since the
      Makefile body is testing-evals'). `docker compose up` smoke: **found and worked
      around a blocking bug in the shared `docker-compose.yml` (see Integration
      deltas) — not this feature's file to fix.** Verified `/healthz` returns 200 and
      `/ws/call` behaves correctly (greeting, transcript echo, state frames, and —
      after hardening `app/ws/routes.py` to catch TTS/LLM exceptions per turn instead of
      letting them kill the connection — graceful degradation to a spoken fallback line
      when OpenAI calls fail) by building the real Dockerfile image and running it
      against a manually-networked Postgres 18 container (compose's own db service
      can't start due to the bug below).
- [ ] Tick roadmap Phase 1 `[x]` in `specs/constitution/roadmap.md` — deferred to the
      lead: DoD also requires `make transcript`/`make eval` green, which depend on
      testing-evals' harness landing first (COORDINATION.md §5 integration order).

## Integration deltas

Shared files this feature needed but doesn't own — the lead applies these at merge
time (COORDINATION.md §3):

- **`.gitignore`**: add `web/next-env.d.ts` and `web/tsconfig.tsbuildinfo` (Next.js
  regenerates both locally; neither should be committed). Deleted them from this
  worktree rather than committing, but a stray `git add -A` elsewhere could reintroduce
  them without this entry.
- **`pyproject.toml`**: no new runtime deps were needed beyond the Phase 0b foundation
  list — `llama-index-llms-openai`'s `FunctionCallingLLM`/`AgentWorkflow` surface and
  `openai`'s streaming TTS client covered everything this feature needed.
- **`Makefile`**: `dev`, `web-dev`, and `migrate` bodies were filled in directly (the
  foundation scaffold's own per-target comments assign these three to
  voice-diagnostic-core); `test`, `lint`, `transcript`, `eval`, `up`, `deploy` were left
  untouched (owned by testing-evals / deployment-deliverables per COORDINATION.md §3).
- **`docker-compose.yml` — BLOCKING for mission non-negotiable 3 (single-command
  launch), found while running the group-7 Compose smoke test**: the `db` service's
  `postgres:18-alpine` container fails to start with *any* fresh named volume mounted
  at `db_data:/var/lib/postgresql/data` — Postgres 18's image changed its expected
  layout and now wants a single mount at `/var/lib/postgresql` (the entrypoint refuses
  to start, logging "in 18+, these Docker images are configured to store database data
  in a format which is compatible with pg_ctlcluster..." and pointing at
  https://github.com/docker-library/postgres/issues/37). Fix: change the volume line to
  `db_data:/var/lib/postgresql` (drop the `/data` suffix). Reproduced with a completely
  fresh volume (`docker compose down -v` first) — this isn't stale local state, it
  reproduces for every fresh clone. Worked around it for this feature's own testing by
  running Postgres in a separately networked container instead of through Compose;
  `docker compose up` itself is broken until this one-line fix lands.
  **APPLIED 2026-07-08** (lead, Docker-storage change): compose `db` volume now mounts
  `db_data:/var/lib/postgresql`; verified against a fresh volume.
