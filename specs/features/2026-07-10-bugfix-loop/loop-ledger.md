# Bugfix loop — ledger

state: running
iterations: 1
consecutive_failures: 0
dry_discovery_passes: 0
seeded_from: 20-teammate test-coverage audit, 2026-07-10 (session ea595583)

Conventions: one item per iteration; test-first; accept only on green
`make test`; commit only touched files (collaborator dirt stays put);
this file is the single source of truth for the loop.

## Queue

| id | pri | kind | status | item |
|----|-----|------|--------|------|
| B1 | P0 | bug+test | done (i1) | Safety detector false negatives (`app/agent/safety.py`): "is smoking", "water in/on the outlet/wiring", "smell of gas", "propane smell", "arcing" don't trip the hazard interrupt. Add recall suite (participle/preposition/synonym phrasings + negation behavior pinned), extend regexes. Mission non-negotiable #1. |
| B2 | P0 | bug+test | open | Upload endpoint buffers entire body before 413 check (`app/uploads/routes.py:94`) — enforce size cap during/before read on the public unauthenticated endpoint; test that an oversize POST rejects without full buffering. |
| B3 | P1 | bug+test | open | TTS cache prewarm gates on `OPENAI_API_KEY` while default web TTS provider is Cartesia (`app/agent/tts_cache.py`) — Cartesia-only deploy never warms cache. Fix gate to match active provider; test both provider configs. |
| B4 | P1 | bug+test | open | Cloudflare env drift: `UPLOAD_TOKEN_SECRET` missing from `APP_CONTAINER_ENV_NAMES` in `cloudflare/app-worker.ts` (never reaches hosted container); `CF_EMAIL_API_URL` in allowlist but absent from `.env.example`. Fix both; add worker-allowlist ↔ `.env.example` consistency test. |
| B5 | P2 | bug+test | open | GET upload status maps `failed` records to reason `already_used` (`app/uploads/routes.py` status projection) — report distinct `analyzed`/`failed` reasons; test both branches. |
| B6 | P2 | bug+test | open | `latency_compare` prints perceived phone budget (2500) beside pass flag computed against meaningful (3200) (`scripts/latency_compare.py`) — align label with gated budget; pin with test. |
| T1 | P1 | test | open | `app/contracts.py` direct guards: CaseFile field set/defaults, Appliance pinned to six literals, WS frame discriminants + AudioFrame format literals; plus parity test vs `web/lib/types.ts` (fields match today — guard the drift). |
| T2 | P1 | test | open | Alembic behavioral test: `alembic upgrade heads` on a throwaway Postgres reaches head (0004 merge coexists both branches); downgrade round-trip. Skip-loudly if no DATABASE_URL, mirroring the scheduling lane convention. |
| T3 | P1 | test | open | Parametrize the upload-store lifecycle suite over InMemory AND Postgres backends (`tests/test_visual_upload_store.py` currently InMemory-only); cover `save_image`/`mark_failed` on unknown token failing cleanly. |
| T4 | P1 | test | open | SMTP backend `send()` path (`app/email/backend.py`): implicit-TLS (465) vs STARTTLS branch kwargs via mocked aiosmtplib, failure propagation, unknown/mixed-case `EMAIL_BACKEND` fallback. |
| T5 | P1 | test | open | Booking bench harness: `run_bench` `finally` self-cleanup leaves DB as found; `ToolWiretap` preserves LLM-visible tool schema (`__annotations__`/`__doc__`, no `*args`) — the documented 2026-07-09 footgun; aggregate `overall_pass` gate. |
| T6 | P2 | test | open | Prompt-refresh pipeline assertions: SystemPromptRefreshProcessor refreshes on TranscriptionFrame (and only then); safety-swallowed turn skips refresh + LLM; insert-branch when context head isn't system (`app/voice/processors.py`). |
| T7 | P2 | test | open | Eval harness: hermetic `drive_adaptive` loop test with FakeFunctionCallingLLM (convergence, safety short-circuit behavioral not source-string); add canaries for `photo_findings` and `conversation_completeness`. |
| T8 | P2 | test | open | Prompts: `_knowledge_vocabulary` both branches asserted in built prompt; IMAGE_UPLOAD_CONTRACT presence + spell-back/tool directives pinned (`app/agent/prompts.py`). |
| T9 | P2 | test | open | Scheduling confirmation payload: booking confirm returns exact `starts_at`/`ends_at` of claimed slot (verbal read-back data); appliance-inference alias table incl. hvac aliases (`a/c`, ` ac `, furnace, thermostat). |
| T10 | P2 | test | open | Knowledge loader negative path: malformed/empty on-disk YAML rejected via `load_knowledge` (not direct model construction); safety-tree script content asserted for all six appliances; `get_symptom_tree` unknown-appliance path. |
| T11 | P2 | test | open | Budgets/obs: E2EBudget `p50 < p95` for every channel; meaningful ≥ perceived; latency-probe positive flag mount on real app; startup hooks fire under `with TestClient(app)`. |
| T12 | P2 | test | open | Instrumentation branches (`app/agent/instrumentation.py`): TTFT event, usage-token extraction (object+dict), ExceptionEvent, `_MAX_TRACKED` eviction, span handler qualname filter/error path; `run_turn` contextvar reset on mid-turn disconnect. |
| T13 | P3 | test | open | web/ vitest bootstrap + lib suite: add vitest+jsdom runner; `UtteranceAudioBuffer` byte-vs-base64, `CallSocket` dispatch/format normalization, `AudioPlaybackQueue` ordering + `stopAndClear`, `PcmPlaybackQueue` PCM16 decode/gapless scheduling, `session.ts`, pure formatters. |
| T14 | P3 | test | open | Uploads security edges: path-traversal token → 404 (regression guard), magic-byte vs declared content-type behavior pinned, concurrent single-use TOCTOU (exactly one 200). |
| T16 | P2 | flake | open | Scheduling DB lane + stutter pacing probe flake under CPU load (observed i1: full-suite run 18F/4E in tests/scheduling, then one pacing FAIL; all pass quiet). Investigate load sensitivity — serialize DB lane or add load-aware retry/backoff to the pacing probe median. |
| T15 | P3 | test | open | Misc thin edges: `for_call(None)` uuid4 fallback + `bind()` reset semantics (`app/voice/session.py`); `_log_metric` TTFA/LLM/TTS branches (`app/voice/metrics.py`); `SpeechPipeline` emit-failure containment (`app/agent/tts_pipeline.py`); webhook TwiML-build-failure → 500; `customParameters.CallSid` fallback. |

## Iterations

### i1 — B1: safety detector recall (accepted)

- Test-first: new `tests/test_safety_recall.py` (31 cases) — 24 failed against the
  unfixed regexes, confirming every audit false negative ("is smoking", "smoky",
  "water in/on/onto the outlet/wiring", "wet outlet", "dripping onto the plug",
  "smell of gas/burning", propane smell/leak, fumes, arcing).
- Fix: `app/agent/safety.py` — smoke matches participle/adjective forms
  (smoking/smoky, `smoked` still excluded); gas gains `smell of`, propane and
  fumes constructions (bare "propane range" ownership still clean); burning gains
  `smell of burning/burnt`; sparking gains arc/arcing/arced; water pattern gains
  in/into/inside/on/onto/under/behind connectives plus wet-electrics and
  leak/drip-onto-electrics clauses, with shared `_ELECTRICS`/`_PROXIMITY`
  fragments so directions can't drift. All pre-existing false-positive guards
  (sparkling, smoked, water-far, wet clothes) still pass. Negation over-trigger
  pinned by design.
- Gates: stutter PASS, `pytest tests -q` 1344 passed, `make transcript` PASS.
  Note: first `make test` run flaked in `tests/scheduling` (18F/4E) and a retry
  flaked the stutter pacing probe — both under heavy CPU load from the audit
  fleet shutdown; each passed in a quiet environment. Logged as follow-up T16.
- Files: app/agent/safety.py, tests/test_safety_recall.py.

## Discovery passes

(none yet)

## Discovery passes

(none yet)
