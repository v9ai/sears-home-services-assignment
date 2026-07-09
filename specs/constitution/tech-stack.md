# Tech Stack

## Runtime

- **Python 3.12**, **FastAPI + uvicorn**, single app container.
- **WebSocket** session channel at `/ws/call`: JSON text messages in, transcript events
  and streamed TTS audio chunks out — the web/debug channel (`app/ws/routes.py`), which
  runs the LlamaIndex agent (`run_turn`) directly.
- **Telephony (phone channel)**: Twilio Programmable Voice + Media Streams (bidirectional
  WS, base64 μ-law 8 kHz) handled by a **Pipecat** pipeline (`app/voice`, feature
  `2026-07-09-pipecat-voice-port`): Pipecat's Twilio serializer + FastAPI WebSocket
  transport replace the former hand-rolled codec/resample/`SessionBridge` adapter.
  `X-Twilio-Signature` is validated on the `/twilio/voice` webhook (`app/phone/webhook.py`,
  retained); ngrok Compose profile for dev exposure. The web (`/ws/call`) and phone
  (`/ws/twilio`) channels are now **two separate implementations** — not one shared
  session bridge — reusing the same tools/prompts/guardrails/knowledge.

## Frontend

- **Next.js (App Router, TypeScript)** in `web/` — chat page (text input, live
  transcript, auto-playing TTS audio queue, case-file panel) and the Tier 3 upload page
  (`/upload/[token]`).
- Talks to the FastAPI backend over REST + WSS (`NEXT_PUBLIC_API_URL`,
  `NEXT_PUBLIC_WS_URL`); the FE is a **thin client** — no agent, model, or business
  logic in the browser; all OpenAI calls stay server-side.
- Local single-command launch: a `web` service in Compose runs the same app, so
  `docker compose up` remains self-sufficient without any cloud account.

## Hosting (Cloudflare Containers)

- Hosted deploys run on **Cloudflare Containers** (Workers-routed containers, deployed
  with `wrangler deploy`): the **same Dockerfiles** Compose uses build the `web` and
  `app` container images — no separate build path.
- Hosted topology is fixed for the demo: two Workers and two singleton containers.
  `AppContainer` uses the root `Dockerfile`, port `8000`, `instance_type = "basic"`,
  `max_instances = 1`, and `getContainer(APP_CONTAINER, "singleton").fetch(request)`;
  `WebContainer` uses `web/Dockerfile`, port `3000`, `instance_type = "basic"`,
  `max_instances = 1`, and `getContainer(WEB_CONTAINER, "singleton").fetch(request)`.
- Workers terminate HTTP + **WebSockets**, which is what `/ws/call` and the Twilio
  Media Streams bridge (`/ws/twilio`, Phase 5) need — the hosted backend has a public
  WSS URL without ngrok.
- App runtime config is passed from Worker vars/secrets into the app container via
  `Container.envVars`; storing secrets on the Worker but not passing them into the
  container is not a valid hosted configuration.
- Frontend public backend URLs (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`) are
  Cloudflare container `image_vars` for the `web` image because Next.js bakes them at
  build time.
- ngrok stays a **local-dev-only** convenience for Twilio webhooks against a laptop.
- Postgres is **not** containerized on Cloudflare — hosted deploys point `DATABASE_URL`
  at **Neon** (managed Postgres); locally the Compose `db` service remains. Use Neon's
  **pooled** connection string for the app (asyncpg through PgBouncer) and the
  **direct** connection string for Alembic migrations.

## Agent framework

- **LlamaIndex** (`llama_index.core.agent.workflow`): a single `FunctionAgent` run via
  `AgentWorkflow`, tools as plain async Python functions. Tool/function calling runs
  through LlamaIndex's `FunctionCallingLLM` interface — the provider is swappable at
  the single factory `app/agent/core.py:get_llm()` (DeepSeek by default, see Models).
- **Memory**: LlamaIndex `ChatMemoryBuffer` per session **plus** a structured pydantic
  **case file** persisted to Postgres and injected into the system prompt every turn —
  this is what makes mission non-negotiable 2 ("never re-ask") structural.
- **Voice pipeline (phone channel)**: **Pipecat** owns the real-time phone pipeline
  (`app/voice`) — transport → STT → LLM → TTS. The Pipecat LLM service runs the
  function-calling loop directly; every LlamaIndex tool is re-exposed as a Pipecat
  function-calling tool (`app/voice/tools.py`) that calls the same `app/tools/*` function,
  so **LlamaIndex still owns retrieval/RAG, prompts, guardrails, and the knowledge base**.
  The pre-LLM safety gate (`detect_safety_trigger`), the per-turn case-file-in-prompt
  refresh (never-re-ask), and spoken-text sanitizing are Pipecat frame processors
  (`app/voice/processors.py`); conversation memory is Pipecat's context aggregator.

## Models

| Role   | Model                | Notes                                                        |
|--------|----------------------|--------------------------------------------------------------|
| LLM (web agent) | **DeepSeek `deepseek-chat`** | direct `api.deepseek.com` via `llama-index-llms-deepseek` (`DeepSeek`, a `FunctionCallingLLM`); `DEEPSEEK_MODEL` override; `LLM_PROVIDER=openai` falls back to `gpt-4o`; `deepseek-reasoner` rejected — no function calling. See `2026-07-08-deepseek-agent-llm/`. |
| LLM (phone/Pipecat) | **OpenAI `gpt-4o`** | the Pipecat voice-pipeline LLM (`VOICE_LLM_MODEL`, `app/voice/bot.py`); chosen for reliable real-time tool-calling; `LLM_PROVIDER=deepseek` swaps in `deepseek-chat` for parity. Sanctioned exception to the Model-provider boundary — see the amendment below. |
| TTS    | `gpt-4o-mini-tts`    | streamed, steerable "warm service agent" voice; phone channel via Pipecat (`TTS_PROVIDER` swappable to Cartesia / Deepgram Aura-2) |
| Vision | **GPT-4 Vision** via `gpt-4o` | the assignment's "GPT-4 Vision" option — `gpt-4o` is its current API (the `gpt-4-vision-preview` endpoint is retired); chat-with-image, JSON-schema response (Tier 3) |
| STT    | **Deepgram** (streaming) | phone-channel default (`app/voice`, `DEEPGRAM_API_KEY`); `STT_PROVIDER=openai` → `gpt-4o-transcribe`/`whisper-1` |

## Database

- **PostgreSQL 18** — Compose service `db` locally (`postgres:18-alpine`); **Neon** for
  hosted deploys (same `DATABASE_URL` contract, no code difference). Neon project:
  `damp-shape-82273628` (`sears-home-services-assignment`, aws-us-east-1, db `neondb`,
  PG 18 — provisioned and connection-verified 2026-07-08).
- **SQLAlchemy 2.0 async** (asyncpg) + **Alembic** migrations. Explicit `select()`s only.
- Idempotent seed script (`make seed`): 8 technicians across ~6 zip codes covering all six
  appliance specialties, with a two-week rolling slot horizon.

## Make commands

| Command           | Does                                                            |
|-------------------|-----------------------------------------------------------------|
| `make up`         | `docker compose up --build` — the single-command launch          |
| `make dev`        | local uvicorn with reload against the Compose db                 |
| `make web-dev`    | `next dev` in `web/` against the local backend                   |
| `make migrate`    | `alembic upgrade head`                                           |
| `make seed`       | idempotent technician/slot seed                                  |
| `make test`       | pytest                                                           |
| `make lint`       | `ruff check` + `ruff format --check`                             |
| `make transcript` | scripted text-mode E2E conversation gate (hard pass/fail)        |
| `make eval`       | **DeepEval** conversational gate over the transcript scenarios   |
| `make eval-voice` | Pipecat voice-channel gates: `tests/voice` (offline) + DeepEval over spoken output |
| `make eval-live`  | required final live-agent transcript/eval gate (to implement)    |
| `make ingest`     | build the local Qdrant appliance-library index (Phase 6, opt-in) |
| `make phone-debug`| Twilio CLI debug toolkit (`scripts/twilio_debug.py`, Phase 5 aid)|
| `make latency`    | per-stage latency bench + budget report (Phase 8)               |
| `make deploy`     | `wrangler deploy` of `app` + `web` to Cloudflare Containers      |

## Evaluation (DeepEval)

Two-layer conversation gating, both hard pass/fail:

1. **`make transcript`** — deterministic structural assertions over scripted
   conversations (case-file contents, broad no-reask memory, safety routing, booking
   row present, grounded troubleshooting steps where applicable).
2. **`make eval`** — **DeepEval** (pytest-integrated) conversational metrics judged by
   **DeepSeek `deepseek-chat`** (Model-provider boundary, 2026-07-08; previously
   `gpt-4o` — the judge-provider-diversity rationale is superseded, and the
   self-grading bias risk is mitigated by the mandatory canary suite, which must fail
   on every run) — over the scenario transcripts: **Knowledge Retention** (the
   never-re-ask non-negotiable, measured), **Role Adherence** (warm service-agent
   persona), **Conversation Completeness** (caller's issue resolved or escalated), and
   custom **G-Eval rubrics per feature** — safety interrupt (Tier 1), booking
   confirmation read-back (Tier 2), photo-findings incorporation (Tier 3).
   Expanded test-class set (PDF-grounded, 2026-07-08): memory, persona, completeness,
   feature rubrics, plus **elicitation** (vague callers), **greeting/rapport**,
   **groundedness** (advice must trace to the knowledge YAMLs — dual structural+judged),
   **injection-resistance & out-of-domain robustness**, **tool-selection accuracy**,
   **consistency (3× @ temp 0)**, **latency (advisory-first)**, tool trace +
   critical-argument validation, and a **vision golden set** (Tier 3-claim only) —
   traceability table in the testing-evals spec.
   Scenario matrix, metric config, and pinned thresholds live in `evals/` and are
   specified in `specs/features/2026-07-08-testing-evals/`; a failing metric blocks the
   feature like any other gate. Judge calls use `DEEPSEEK_API_KEY`
   (`EVAL_JUDGE_PROVIDER=openai` opts back into `gpt-4o`); `make eval` is
   skipped-with-warning when the active provider's key is absent, never silently green.
**Voice-channel eval (`make eval-voice`, 2026-07-09 pipecat-voice-port):** the Pipecat
phone channel is gated two ways. (a) **Offline structural tests** (`tests/voice`, run by
`make test`): tool-output parity (each ported Pipecat tool returns byte-identical output to
its LlamaIndex origin), guardrail parity (the pre-LLM safety gate fires on exactly the
scenarios the web gate does, over the whole matrix), schema parity (the `FunctionSchema`s
match the frozen tool contract), pipeline assembly, and provider-swap selection. (b) A
**DeepEval conversational gate over the spoken output** (`evals/test_voice_conversations.py`):
each scenario transcript is run through the voice channel's `SpokenTextSanitizer`
(`evals/voice_fixture_lens.voice_lens`) and scored with the same metrics/thresholds/judge as
`make eval`, proving persona/retention/safety survive TTS-clean spoken delivery. Same
judge-key skip-with-warning posture as `make eval`.

3. **`make eval-live`** — final integrated-agent acceptance (to implement): real agent,
   migrated/seeded DB, live transcript recording, and the same structural + judged
   checks over web and required Twilio phone evidence. The PDF voice path is not
   submission-ready until a real phone transcript passes greeting, diagnosis,
   no-reask, safety, scheduling, STT→agent→TTS, and latency-report checks.

## Model-provider boundary (BINDING — user directive 2026-07-08)

**Every text-LLM call runs on DeepSeek. OpenAI is permitted ONLY for the modalities
DeepSeek does not offer: vision, speech-to-text, and text-to-speech.**

- Agent LLM: DeepSeek `deepseek-chat` (`app/agent/core.py:get_llm()`).
- DeepEval judge: DeepSeek `deepseek-chat` (`evals/thresholds.py:judge_model()`).
- Any future text-generation call (summaries, emails, classification, library RAG
  synthesis) MUST use DeepSeek via the LlamaIndex `FunctionCallingLLM`/OpenAI-compatible
  path — adding an OpenAI text-LLM call is constitution-revising.
**Amendment (2026-07-08, later same day)** — user directive "swap with OpenAI":
the shipped demo-day default is now `LLM_PROVIDER=openai` in `.env.example`
(latency-engineering P2-2 exercised; first A/B sample — DeepSeek 4.07 s first
sentence / 11.79 s full turn vs gpt-4o 6.16 s / 7.54 s: full-turn faster,
first-sentence slower; single samples, perceived lag dominated by tool round-trips —
P0 fixes remain the priority). The DeepSeek code default and this boundary section
otherwise stand; unsetting `LLM_PROVIDER` returns to DeepSeek. The DeepEval judge
stays on DeepSeek. **Model pin (same day, "use fastest openai model"):**
`OPENAI_LLM_MODEL=gpt-4.1-mini` — won the N=3 live-turn sweep (4.29 s median first
sentence, 3/3 tools-correct; confirmation run 3.74 s / 9.03 s). gpt-4.1-nano was
faster raw but skipped tools 2/3 (disqualified); gpt-5-family reasoning models were
28–41 s to first word — unusable for voice. Full table:
`2026-07-08-latency-engineering/` P2-2.
**Amendment (2026-07-09, Pipecat voice port)** — the phone channel's real-time voice
pipeline (`app/voice`, `2026-07-09-pipecat-voice-port`) runs the **Pipecat LLM service on
OpenAI `gpt-4o` by default** (`VOICE_LLM_MODEL`), because the Pipecat pipeline drives the
tool-calling loop itself and OpenAI's function-calling is the reliable low-latency choice
for a live call. This is a **sanctioned, explicit exception** to "every text-LLM call runs
on DeepSeek": it is confined to the voice pipeline, documented here and in the Models
table, and `LLM_PROVIDER=deepseek` swaps the voice LLM back to `deepseek-chat` (one env
var) for parity. The **web agent LLM and the DeepEval judge stay on DeepSeek**; STT moving
to Deepgram means STT is no longer an OpenAI modality on the phone channel at all. Any
automated provider-allowlist test must whitelist the voice pipeline's OpenAI LLM
construction (`app/voice/bot.py`) alongside the existing two env-gated hatches.

- Escape hatches, env-gated and off by default: `LLM_PROVIDER=openai` (agent fallback,
  demo-day resilience) and `EVAL_JUDGE_PROVIDER=openai` (judge, when a funded OpenAI
  key exists). Using either is a recorded event, not a silent default.
- Recorded tradeoff: agent and judge now share a provider (self-grading bias risk);
  the mitigation is the mandatory canary suite — the judge must provably fail bad
  transcripts on every run (testing-evals Decision 3).

**LlamaIndex-native evaluation (adopted 2026-07-08, verified 0.14.23):** alongside the
DeepEval conversational gate, LlamaIndex's own evaluation stack is used where DeepEval
has no native equivalent — `RetrieverEvaluator` (HitRate/MRR) for the Phase 6 library
retriever, `DatasetGenerator` for corpus-derived eval questions,
`FaithfulnessEvaluator` for per-response groundedness against the knowledge trees, and
`llama_index.core.instrumentation` events for tool-selection tracing. Every LLM-judged
LlamaIndex evaluator runs on DeepSeek via `get_llm()` (Model-provider boundary);
adoption map + skip rationale in `specs/features/2026-07-08-testing-evals/`.

## Forbidden patterns

- **OpenAI for text-LLM calls** — see the Model-provider boundary above; OpenAI is
  vision/STT/TTS only. An automated provider-allowlist test must fail on OpenAI
  text-generation construction outside the two env-gated escape hatches.
- **No LangChain / LangGraph** — LlamaIndex is the sole agent framework.
- **No OpenAI Realtime API** — it collapses STT→LLM→TTS into one opaque model, hiding the
  seams the design doc must demonstrate. The Pipecat phone pipeline (`app/voice`) is
  **discrete-service** (separate Deepgram STT, LLM, and TTS stages the LLM tool-loop sits
  between), so it stays compliant with this rule while gaining a maintained transport.
- **No vector DB / embeddings on the primary diagnostic path** — deterministic keyed
  YAML lookup stays authoritative (voice-diagnostic-core Decision 3). Sole sanctioned
  exception: the **flag-gated appliance-library Qdrant index**
  (`2026-07-08-appliance-library-qdrant/`, spike-verified 2026-07-08) — embedded local
  Qdrant + FastEmbed local embeddings, augmentation-only fallback behind
  `LIBRARY_RAG_ENABLED` (default off), never ahead of the safety pre-filter.
- **No raw SQL string interpolation** — parameterized SQLAlchemy only.
- **No hand-applied schema changes** — Alembic only.
- **Telephony (PSTN) = Twilio only** — no other *telephony/PSTN* provider SDKs
  (Vonage/Plivo/Telnyx); Twilio code lands under its feature triplets. This rule governs
  the **phone carrier**, not the media pipeline: the Pipecat phone channel
  (`2026-07-09-pipecat-voice-port`) is sanctioned to use non-Twilio **media** SDKs —
  **Deepgram** STT, **Silero** VAD, and optionally **Cartesia** TTS — via Pipecat services.
  Twilio remains the sole PSTN ingress (webhook/TwiML/Media Streams serializer).
- **No agent/LLM logic in the frontend** — the Next.js app renders and relays; every
  OpenAI/LlamaIndex call happens in the FastAPI backend.

## Observability

- Logs go to stdout/stderr as structured key/value records; no external APM/tracing
  backend is required for the take-home.
- Twilio phone logs are a hardened contract: every call is correlated by
  `session_id`, `call_sid`, `stream_sid`, and hashed caller/called numbers; event names
  are stable and tested (`specs/features/2026-07-08-telephony-twilio/`).
- Phone traces cover the webhook (`app/phone/webhook.py`, retained) and — since the media
  transport is now Pipecat (`app/voice`) — the Pipecat pipeline's lifecycle, Silero VAD,
  Deepgram STT, the LLM tool loop, TTS, barge-in/interruptions, and per-call metrics
  (`PipelineParams(enable_metrics=True)`), plus the voice frame processors
  (`voice_safety_interrupt`, prompt refresh, sanitizer). The former hand-rolled
  `twilio.*` bridge/VAD/STT events (`app/phone/{routes,bridge,vad}.py`) are retired with
  that code; `llama.*` LLM/tool tracing (`app/agent/instrumentation.py`) is unchanged.
- Logging must be privacy-safe by default: no raw phone numbers, transcript text,
  Twilio signatures, media payloads, upload links, emails, API keys, auth tokens, or
  database URLs with passwords. Log typed failure events and sanitized exception
  classes instead of request bodies or secret-bearing payloads.
- OpenTelemetry is deferred; if added later, it must preserve the same redaction and
  correlation fields rather than introducing a second trace vocabulary.
- **Structured event core** (`app/obs.py`, 2026-07-09-observability-tracing):
  `log_event(logger, event, **fields)` emits one grep-able `event=<name> key=value...`
  line; `bind_call_context(session_id=, call_sid=, turn_index=)` binds correlation ids
  once per call/turn via a contextvar so every event — including ones raised deep
  inside llama-index — carries them automatically, without threading ids through
  every call site.
- **LlamaIndex full tracing** (`app/agent/instrumentation.py`): registers on
  llama-index's own dispatcher (`llama_index.core.instrumentation`) at startup — no
  third-party APM. Logs every LLM call start/TTFT/end and embedding batch as
  `event=llama.*`; tool calls are logged from `run_turn`'s own `ToolCall` workflow
  event, not the dispatcher (the installed llama-index-core's `AgentWorkflow` never
  dispatches `AgentToolCallEvent` — confirmed dead in this version, documented in the
  module). Per-turn LLM/tool counts fold into the existing `turn_trace` line
  (`app/agent/trace.py`) so one line summarizes a turn's full anatomy.

## Secrets & API key management (`.env.example` is the contract)

### Classification

| Class | Variables | Rules |
|---|---|---|
| Public frontend config | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` | May be baked into the web bundle and Cloudflare `image_vars`; no other env var may reach frontend runtime or build artifacts. |
| Backend secrets | `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY` (optional, only if `TTS_PROVIDER=cartesia`), `DATABASE_URL`, `DATABASE_URL_DIRECT`, `CF_EMAIL_API_TOKEN`, `SMTP_PASSWORD`, `TWILIO_AUTH_TOKEN`, `NGROK_AUTHTOKEN` | Backend container only; never exposed to `web`, client JS, docs, logs, or screenshots. `DEEPGRAM_API_KEY` powers the phone-channel STT (and Aura-2 TTS when `TTS_PROVIDER=deepgram`). |
| Backend non-secret config | `LLM_PROVIDER`, `DEEPSEEK_MODEL`, `OPENAI_LLM_MODEL`, `VOICE_LLM_MODEL`, `STT_PROVIDER`, `TTS_PROVIDER`, `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE`, `OPENAI_VISION_MODEL`, `OPENAI_STT_MODEL`, `OPENAI_STT_USE_FALLBACK`, `OPENAI_TTS_SAMPLE_RATE`, `CARTESIA_VOICE_ID`, `DEEPGRAM_AURA_VOICE`, `APP_BASE_URL`, `EMAIL_BACKEND`, `EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `TWILIO_ACCOUNT_SID`, `TWILIO_PHONE_NUMBER`, `PUBLIC_HOST`, `UPLOAD_DIR` | May be passed to the backend; may be documented by name and example shape, not by real value if environment-specific. `OPENAI_STT_*` apply only when `STT_PROVIDER=openai`. |
| Deploy secrets | `CLOUDFLARE_API_TOKEN` | Host/CI only for Wrangler; never passed into app/web containers or committed. |
| Reserved | `UPLOAD_TOKEN_SECRET` | Not used while upload tokens are random DB-backed rows; if activated later, it becomes a backend secret. |

### Enforcement policy

- `.env.example` is the only committed env file and contains placeholders only. Real
  credentials are supplied via local `.env`, host env vars, `wrangler secret put`, or a
  time-limited reviewer secret link.
- Local Compose must not pass the full `.env` into `web`; the frontend receives only
  `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL`.
- Cloudflare `web` must receive only public `image_vars`. No Worker secret, backend env,
  database URL, model key, Twilio auth token, SMTP password, or Cloudflare token may
  reach `WebContainer`.
- Cloudflare `app` must pass backend secrets explicitly via `Container.envVars`; keeping
  a secret on the Worker but not passing it into the container is invalid, and passing
  any frontend-only public var as a secret is unnecessary.
- Logs and errors may name missing env vars, but must never print key values,
  `Authorization`/`Bearer` headers, auth tokens, SMTP passwords, or database URLs with
  passwords. DB URL rendering outside the driver boundary must hide passwords.
- Test fixtures may use fake values only when clearly labeled, e.g.
  `test-auth-token-not-a-secret`.
- Submission docs may name credentials and describe the secure handoff method; they must
  never contain credential values.
