# Coordination — parallel execution by independent agents

This is the fourth constitution doc (per `specs/_sdd/constitution.md` §2): the contract
that lets **all feature triplets start in parallel**, each driven by an independent
Claude Code (Sonnet) agent, with zero write conflicts and a deterministic integration
order. Every parallel agent reads this file plus its own triplet before writing code.

## 1. The foundation commit (lead does this once, before any parallel start)

A single scaffold commit pre-seeds every **shared** file so no parallel agent ever edits
one:

- `app/contracts.py` — the frozen contracts (§2) as pydantic models + `Protocol`s.
- `pyproject.toml` — ALL dependencies for every feature (fastapi, uvicorn,
  llama-index-core, llama-index-llms-openai, llama-index-llms-deepseek,
  sqlalchemy[asyncio], asyncpg, alembic, openai, pydantic, pyyaml, httpx, aiosmtplib,
  twilio, ruff, pytest, pytest-asyncio, deepeval).
- `Makefile` — ALL targets from `tech-stack.md`, stubbed to no-op with a TODO where the
  owning feature fills in.
- `docker-compose.yml` — `db` + `app` + `web` skeleton; `phone` profile placeholder.
- `alembic/` env wired; `app/` package skeleton (`main.py` with `/healthz`,
  empty `ws/ agent/ tools/ knowledge/ db/ email/ uploads/ vision/ phone/` packages);
  `web/` Next.js scaffold; `tests/` + `evals/` skeletons.
- Tool auto-discovery: `app/tools/registry.py` walks `app/tools/*.py` for a module-level
  `TOOLS: list` — **adding a tool = adding a file**, never editing a shared registry.

After this commit, the ownership map (§3) makes every write exclusive.

## 2. Frozen contracts (changing one = constitution-revising, coordinate first)

All in `app/contracts.py`, mirrored verbatim from the feature specs:

- **Appliance enum**: `washer | dryer | refrigerator | dishwasher | oven | hvac`.
- **`CaseFile`** pydantic model — exact shape in
  `2026-07-08-voice-diagnostic-core/requirements.md` § Contract shapes.
- **WS frames** — `user_text` in; `transcript` / `audio` / `state` out (same spec).
- **`SessionBridge` protocol** — `receive_user_utterance(text)` /
  `emit_transcript(role, text)` / `emit_audio(chunk)` (telephony spec § Contract shapes).
- **Tool signatures** — `identify_appliance`, `record_symptom`,
  `get_troubleshooting_steps(appliance, symptom_key)`, `update_case_file`,
  `find_technicians(zip, appliance_type, window?)`,
  `book_appointment(slot_id, customer, issue_summary)`,
  `send_image_upload_link(email)`, `check_image_analysis()`,
  `search_appliance_library(query)` (Phase 6, flag-gated — registers only when
  `LIBRARY_RAG_ENABLED` is on).
- **Alembic revision IDs, pre-allocated**: `0001_core` (down=None) ·
  `0002_scheduling` (down=`0001_core`) · `0003_visual` (down=`0001_core`).
  Multiple heads are fine during parallel dev (`alembic upgrade heads`); integration
  adds a merge revision.
- **Env var names** — `.env.example` is the contract; no agent renames a var.

## 3. Exclusive ownership map (no agent writes outside its rows)

| Feature (agent) | Owned paths |
|---|---|
| voice-diagnostic-core | `app/ws/`, `app/agent/`, `app/tools/core_tools.py`, `app/knowledge/`, `app/db/models_core.py`, `alembic/versions/0001_core*`, `web/app/(chat)/`, `web/lib/` |
| technician-scheduling | `app/tools/scheduling_tools.py`, `app/db/models_scheduling.py`, `app/db/seed.py`, `app/db/matching.py`, `alembic/versions/0002_scheduling*` |
| visual-diagnosis | `app/email/`, `app/uploads/`, `app/vision/`, `app/tools/visual_tools.py`, `app/db/models_visual.py`, `alembic/versions/0003_visual*`, `web/app/upload/` |
| telephony-twilio | `app/phone/` (webhook, TwiML, codec, VAD, media bridge) |
| testing-evals | `tests/`, `evals/`, `scripts/transcript_runner.py` |
| deployment-deliverables | `Dockerfile*`, `docker-compose.yml` hardening, `wrangler*.toml`, `README.md`, `docs/` |
| appliance-library-qdrant (Phase 6) | `app/tools/library_tools.py`, `app/knowledge/library_store.py`, `scripts/ingest_library.py`, `docs/library/` |

Shared-file changes an agent *needs* but doesn't own (a Makefile target body, a Compose
service tweak, a new dep) are **declared, not made**: list them under "Integration
deltas" in the feature's plan; the lead applies them at merge time.

## 4. Stub seams (how each agent runs standalone before integration)

- **scheduling** — tools + schema are pure Python/SQL against `contracts.CaseFile`;
  test via pytest with a Compose `db`, no agent required.
- **visual-diagnosis** — routes, email module, vision service run standalone; fake a
  session row; `EMAIL_BACKEND=console`; mock the OpenAI vision call in tests.
- **telephony** — implement `SessionBridge` against a `FakeAgent` that echoes scripted
  replies; codec/VAD tested on fixture audio; no live agent needed.
- **testing-evals** — the transcript runner and the DeepEval harness develop against
  **recorded fixture transcripts** (incl. deliberate-failure canaries) until the real
  agent lands; the harness must not import `app.agent`.
- **deployment** — hardens Dockerfiles/Compose/docs against the foundation skeleton
  (`/healthz` suffices for smoke until features merge).
- **voice-diagnostic-core** — the only agent building the real agent loop; owns the
  critical path.

## 5. Integration order (lead-driven, after parallel development)

Status as of 2026-07-08 in **bold** (details: `roadmap.md` → Integration status):

1. **voice-diagnostic-core** merges first (real agent + WS + chat page). **DONE.**
2. **scheduling** and **visual-diagnosis** merge next (tool files auto-discovered;
   Alembic merge revision; their transcript/eval scenarios activate). **DONE**
   (scenarios active; multiple Alembic heads upgraded via `upgrade heads`, merge
   revision still optional).
3. **testing-evals** gates flip from fixture transcripts to live agent runs; all gates
   must be green. **DONE for fixture mode** (CI default, green); live mode shipped
   (`--live`) and pending a real `DEEPSEEK_API_KEY`.
4. **deployment-deliverables** finalizes README/design doc against the integrated
   system; hosted deploy. **MERGED; hosted deploy + no-SKIP fresh-clone smoke
   pending** (`CLOUDFLARE_API_TOKEN`).
5. **telephony-twilio** swaps `FakeAgent` for the real bridge; live-call checklist.
   **MERGED + real-agent adapter applied** (`app/phone/real_agent.py`); Twilio console
   webhook wiring + live-call checklist pending a live `PUBLIC_HOST`.

## 6. Sonnet-sizing rules (how each agent works)

- One plan task-group per working session; groups are sized ≤ ~1 h and end with their
  gate run (`make lint` + owned tests) green.
- Never edit outside the ownership map; needed shared changes go to "Integration
  deltas".
- Follow the per-feature loop in `specs/_sdd/constitution.md` §6; the triplet is the
  only source of truth — do not re-derive decisions.
- Commit per task group with the group name in the message.

## Kickoff prompt template (per agent)

> Read `specs/constitution/{mission,tech-stack,roadmap,COORDINATION}.md`, then your
> triplet `specs/features/<dir>/`. You own ONLY the paths in COORDINATION §3 for your
> feature. Code against `app/contracts.py`; stub per COORDINATION §4. Execute your
> `plan.md` group by group, gates after each group; tick checkboxes as you land them.
> Declare any shared-file needs as "Integration deltas" at the bottom of your plan.md
> instead of editing shared files.
