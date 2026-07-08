# Appliance Library RAG via Local Qdrant — Validation

## Automated
- [ ] `make ingest` idempotent: two consecutive runs produce identical point counts in
      the `appliance_library` collection.
- [ ] Retrieval smoke (pinned from the 2026-07-08 spike): "washing machine loud
      grinding noise" → top-1 `washer/loud_noise` · "smell gas when I turn on the
      oven" → top-1 `oven/safety_gas_smell` with `safety: true` · "fridge not cold
      since yesterday" → top-1 `refrigerator/not_cooling`.
- [ ] Flag-off equivalence: with `LIBRARY_RAG_ENABLED` unset, the tool registry does
      NOT expose `search_appliance_library` and agent behavior is byte-equivalent
      (existing test suite green unchanged).
- [ ] Tool unit (fake store): attributed summary format, k-limit, safety attribution.
- [ ] Library eval scenarios green; retrieval canary red-as-expected.
- [ ] `make lint` + `make test` + `make transcript` clean.

## Manual
1. With the flag on and the library ingested: ask the chat a question outside the six
   YAML trees (e.g. from a `docs/library/` manual) — the agent answers citing the
   library source rather than guessing.
2. Ask a gas-smell question — the safety interrupt fires exactly as before (retrieval
   never runs ahead of the safety pre-filter).
3. Inspect `data/qdrant/` — the index persists across app restarts (named volume).

## Definition of done
- [ ] Each "Included" scope bullet in `requirements.md` is observably true.
- [ ] All automated gates green (canary red-as-expected); flag-off equivalence proven.
- [ ] Constitution updated in the same commit (tech-stack carve-out, `make ingest`,
      roadmap Phase 6, COORDINATION ownership + tool signature).
- [ ] Deferred scope (server mode, hybrid search, re-ranking) recorded above.
- [ ] Roadmap Phase 6 ticked `[x]` only with the flag-on gates green.
