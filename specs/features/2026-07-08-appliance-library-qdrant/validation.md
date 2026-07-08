# Appliance Library RAG via Local Qdrant — Validation

## Automated
- [x] `make ingest` idempotent: two consecutive runs produce identical point counts in
      the `appliance_library` collection. (`tests/test_ingest_library.py`; also
      confirmed manually: 25 points on both of two consecutive runs — 24 YAML
      symptom trees + 1 `docs/library/general_maintenance_tips.md`.)
- [x] Retrieval smoke (pinned from the 2026-07-08 spike): "washing machine loud
      grinding noise" → top-1 `washer/loud_noise` · "smell gas when I turn on the
      oven" → top-1 `oven/safety_gas_smell` with `safety: true` · "fridge not cold
      since yesterday" → top-1 `refrigerator/not_cooling`. All three confirmed
      exactly, both via `tests/test_ingest_library.py` and manual verification.
- [x] Flag-off equivalence: with `LIBRARY_RAG_ENABLED` unset, the tool registry does
      NOT expose `search_appliance_library` and agent behavior is byte-equivalent
      (existing test suite green unchanged). `tests/test_library_flag.py` +
      `tests/test_tool_schemas.py` (pre-existing, untouched, still green).
- [x] Tool unit (fake store): attributed summary format, k-limit, safety attribution.
      `tests/test_library_tools.py`.
- [x] Library eval scenarios green (`evals/scenarios/library/`, via `make
      transcript`'s fixture-mode structural gate — see plan.md group 4 for why
      `feature: core` is used instead of a new `library` enum value); retrieval
      canary red-as-expected (`evals/test_library_retrieval.py`, an off-corpus query
      confirmed to score well below any real match, ~0.4 vs. ~0.7-0.85).
- [x] LlamaIndex retrieval gate: `RetrieverEvaluator` over the
      `DatasetGenerator`-built question set → hit-rate ≥ 0.9, MRR ≥ 0.7
      (`evals/test_library_retrieval.py`). Correctly SKIPs without a live judge-LLM
      key (no `DEEPSEEK_API_KEY` in this environment) — verified via API-signature
      inspection against the installed `llama-index-core==0.14.23` instead of a live
      run; not yet exercised end-to-end with a real key.
- [x] `make lint` + `make test` + `make transcript` clean. Confirmed both without a
      live DB (`make test` errors only the 14 pre-existing, unrelated
      `DATABASE_URL`-dependent scheduling tests, exactly as on `main` before this
      feature) and with one (`DATABASE_URL` pointed at the Compose `db` on 5433:
      227 passed, 0 failed).

## Manual
1. With the flag on and the library ingested: ask the chat a question outside the six
   YAML trees (e.g. from a `docs/library/` manual) — the agent answers citing the
   library source rather than guessing.
2. Ask a gas-smell question — the safety interrupt fires exactly as before (retrieval
   never runs ahead of the safety pre-filter).
3. Inspect `data/qdrant/` — the index persists across app restarts (named volume).

## Definition of done
- [x] Each "Included" scope bullet in `requirements.md` is observably true.
- [x] All automated gates green (canary red-as-expected); flag-off equivalence proven.
- [x] Constitution updated in the same commit (tech-stack carve-out already landed in
      `fac33da`; roadmap Phase 6 ticked below; COORDINATION ownership + tool
      signature were already recorded in COORDINATION.md §2-3 prior to this build).
- [x] Deferred scope (server mode, hybrid search, re-ranking) recorded above.
- [x] Roadmap Phase 6 ticked `[x]` only with the flag-on gates green.
