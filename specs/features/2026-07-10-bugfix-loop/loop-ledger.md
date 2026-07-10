# Bugfix loop — ledger

state: running
iterations: 9
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
| B2 | P0 | bug+test | done (i2) | Upload endpoint buffers entire body before 413 check (`app/uploads/routes.py:94`) — enforce size cap during/before read on the public unauthenticated endpoint; test that an oversize POST rejects without full buffering. |
| B3 | P1 | bug+test | done (i3) | TTS cache prewarm gates on `OPENAI_API_KEY` while default web TTS provider is Cartesia (`app/agent/tts_cache.py`) — Cartesia-only deploy never warms cache. Fix gate to match active provider; test both provider configs. |
| B4 | P1 | bug+test | done (i4) | Cloudflare env drift: `UPLOAD_TOKEN_SECRET` missing from `APP_CONTAINER_ENV_NAMES` in `cloudflare/app-worker.ts` (never reaches hosted container); `CF_EMAIL_API_URL` in allowlist but absent from `.env.example`. Fix both; add worker-allowlist ↔ `.env.example` consistency test. |
| B5 | P2 | bug+test | done (i5) | GET upload status maps `failed` records to reason `already_used` (`app/uploads/routes.py` status projection) — report distinct `analyzed`/`failed` reasons; test both branches. |
| B6 | P2 | bug+test | done (i6) | `latency_compare` prints perceived phone budget (2500) beside pass flag computed against meaningful (3200) (`scripts/latency_compare.py`) — align label with gated budget; pin with test. |
| T1 | P1 | test | done (i7) | `app/contracts.py` direct guards: CaseFile field set/defaults, Appliance pinned to six literals, WS frame discriminants + AudioFrame format literals; plus parity test vs `web/lib/types.ts` (fields match today — guard the drift). |
| T2 | P1 | test | done (i8) | Alembic behavioral test: `alembic upgrade heads` on a throwaway Postgres reaches head (0004 merge coexists both branches); downgrade round-trip. Skip-loudly if no DATABASE_URL, mirroring the scheduling lane convention. |
| T3 | P1 | test | done (i9) | Parametrize the upload-store lifecycle suite over InMemory AND Postgres backends (`tests/test_visual_upload_store.py` currently InMemory-only); cover `save_image`/`mark_failed` on unknown token failing cleanly. |
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
| T16 | P1 | flake | open | Scheduling DB lane + stutter pacing probe flake under CPU load (observed i1 AND i9 — pacing probe failed twice under parallel-session load; all pass quiet). A hard gate that flakes under load erodes every loop that depends on it. Investigate load sensitivity — serialize DB lane or add load-aware retry/backoff to the pacing probe median. |
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

### i2 — B2: upload size cap without full-body buffering (accepted)

- Test-first: new `tests/test_upload_size_cap.py` (4 cases) — declared-oversize
  must reject with zero reads, undeclared-oversize must stop pulling at the cap,
  exactly-at-cap accepted, empty still 400. Three failed against the unfixed
  handler (single unbounded `file.read()` then post-hoc check).
- Fix: `app/uploads/routes.py` — fast-path 413 on declared `file.size`, then a
  1 MB-chunk bounded read loop that 413s as soon as the cap is crossed.
- Gates: stutter PASS, `pytest tests -q` 1348 passed (incl. dirty-file route
  tests untouched). Not agent-flow → no transcript gate.
- Commit isolation: `app/uploads/routes.py` carries pre-existing collaborator
  dirt (uncommitted `_analyze_in_background` retry work). Gates ran against the
  real tree (dirt + fix); the commit stages a fix-only blob via git plumbing so
  the collaborator's uncommitted work stays out of history. Working-tree dirt
  preserved verbatim.
- Files: app/uploads/routes.py (fix-only hunks), tests/test_upload_size_cap.py.

### i3 — B3: provider-aware TTS prewarm gate (accepted)

- Test-first: new `tests/test_tts_prewarm_provider.py` (6 cases) — 3 failed
  pre-fix: Cartesia-only deployment never warmed (headline bug), OpenAI-key-only
  attempted a doomed Cartesia synth, mixed formats not gated per-format.
- Fix: `app/agent/tts.py` gains `provider_env_ready(format)` mirroring the
  synthesize dispatch (single source of truth); `tts_cache.prewarm` now gates
  each format on the provider it would actually route to instead of
  unconditionally on `OPENAI_API_KEY`.
- Collaborator-dirt reconciliation: the uncommitted
  `test_prewarm_noop_without_api_key` in dirty `tests/test_tts_cache.py`
  encoded the old OpenAI-only gate (its env cleanup only removed
  OPENAI_API_KEY); updated its setup in the working tree to clear all provider
  keys — the amendment stays with the collaborator's dirt (test absent from
  HEAD, nothing committed).
- Gates: stutter PASS, `pytest tests -q` 1354 passed.
- Files committed: app/agent/tts.py, app/agent/tts_cache.py (fix-only hunks via
  plumbing; voice-keying dirt preserved uncommitted),
  tests/test_tts_prewarm_provider.py.

### i4 — B4: worker env-forwarding contract (accepted)

- Findings refined the audit: `UPLOAD_TOKEN_SECRET` confirmed absent from
  `APP_CONTAINER_ENV_NAMES` (documented + named as required wrangler secret;
  reserved for the signed-token scheme). `CF_EMAIL_API_URL` was already
  documented (commented optional) — audit claim moot. NEW, bigger drift found:
  the entire voice-provider block (STT_PROVIDER, DEEPGRAM_API_KEY,
  VOICE_LLM_MODEL, TTS_PROVIDER, CARTESIA_API_KEY, CARTESIA_VOICE_ID) was never
  forwarded — hosted phone calls would have had Twilio creds but no STT/TTS
  keys, and hosted web TTS (Cartesia default) no credentials.
- Test-first: new `tests/test_worker_env_contract.py` (5 tests, text-parsing
  style like test_compose_config.py) — bidirectional drift guard between
  `.env.example`, the worker allowlist, and the Env interface, with
  NGROK_AUTHTOKEN pinned compose-only. 3 failed pre-fix.
- Fix: `cloudflare/app-worker.ts` — 7 names added to allowlist + Env interface.
- Gates: stutter PASS, `pytest tests -q` 1359 passed. Standalone `npx tsc`
  shows only pre-existing ambient-type lookups (no workers-types in bare tsc);
  syntax verified.
- Files: cloudflare/app-worker.ts, tests/test_worker_env_contract.py (both
  clean of collaborator dirt).

### i5 — B5: distinct "failed" status reason (accepted)

- Test-first: new `tests/test_upload_status_reasons.py` (6 cases) — the failed→
  "failed" case failed pre-fix (collapsed into "already_used"); pending/expired/
  consumed/not_found projections pinned alongside.
- Fix: `_status_response` gains an explicit "failed" branch; upload page's
  default message branch now applies instead of the misleading "already used".
- Gates: stutter PASS, `pytest tests -q` 1365 passed.
- Files committed: app/uploads/routes.py (fix-only hunks via plumbing; retry
  dirt preserved uncommitted), tests/test_upload_status_reasons.py.

### i6 — B6: compare table shows the gated budget (accepted)

- Test-first: new `tests/test_latency_compare_budget_label.py` (2 tests) — the
  label/gate-consistency case failed pre-fix (phone row showed budgets_ms
  perceived 2500 while the pass flag gated meaningful 3200).
- Fix: `compare()` reads the budget from the e2e summary's own `budget_p50_ms`
  (the budget its pass flag actually used), falling back to `budgets_ms` only
  for legacy reports predating that field.
- Gates: stutter PASS, `pytest tests -q` 1367 passed (incl. the dirty
  test_latency_compare.py suite unchanged).
- Files: scripts/latency_compare.py, tests/test_latency_compare_budget_label.py
  (both clean of collaborator dirt).
- Milestone: all six audit bugs (B1–B6) closed. Queue continues with T1–T16.

### i7 — T1: contract shape guards + types.ts parity (accepted)

- Test-gap item: new `tests/test_contracts_shape.py` (17 tests). Python side:
  Appliance pinned to the six literals, CaseFile defaults + frozen field set +
  unknown-appliance rejection, frame discriminants, AudioFrame format literal,
  wire round-trips, SessionBridge runtime_checkable conformance. Parity side:
  textual parse of `web/lib/types.ts` — every mirrored interface's field set,
  the Appliance union order, and EMPTY_CASE_FILE coverage must equal the
  pydantic contract. Parity verified holding today; drift now fails loudly in
  both directions. No defect exposed, no product change.
- Gates: stutter PASS, `pytest tests -q` 1384 passed.
- Files: tests/test_contracts_shape.py.

### i8 — T2: behavioral alembic migration tests (accepted)

- Test-gap item: new `tests/test_alembic_migrations.py` (2 tests) — real
  `alembic upgrade heads` via subprocess (env.py is async; in-process would
  nest loops) against a dedicated `<db>_test_migrations` database mirroring the
  scheduling-lane isolation convention. Asserts all 8 tables from the 3
  branches + merge, `alembic_version == script heads`, and `sessions.call_sid`
  (rev 0005, post-merge). Second test round-trips `downgrade base` (clean wipe)
  → `upgrade heads` (full restore). Skips loudly without DATABASE_URL.
- Migrations verified genuinely working — the entrypoint's first boot step now
  has behavioral coverage. No defect found.
- Gates: stutter PASS, `pytest tests -q` 1393 passed (count includes tests
  added concurrently by the appt-req-loop session; all green together).
- Files: tests/test_alembic_migrations.py.

### i9 — T3: cross-backend upload-store contract (accepted)

- Test-gap item: new `tests/test_upload_store_postgres.py` — 7 contract tests
  parametrized over InMemoryUploadStore AND PostgresUploadStore (14 runs):
  create/fetch round-trip, unknown-token None, full pending→uploaded→analyzed
  lifecycle, mark_failed terminal past expiry, expired write-back persistence,
  latest_for_session isolation, and the pinned loud-failure mode of mutators on
  unknown tokens (KeyError/AssertionError, no phantom rows). Postgres lane uses
  a dedicated `<db>_test_uploads` database; skips loudly without DATABASE_URL.
- Postgres backend verified matching InMemory semantics — the shipped path is
  no longer untested. No divergence found.
- Gates: first run flaked on the stutter pacing probe (second occurrence —
  T16 bumped to P1); retry green: stutter PASS, `pytest tests -q` 1407 passed.
- Files: tests/test_upload_store_postgres.py.

## Discovery passes

(none yet)
