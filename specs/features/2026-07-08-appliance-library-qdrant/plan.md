# Appliance Library RAG via Local Qdrant — Plan

Flag-gated and additive; implement in dependency order. The feature ships dark
(`LIBRARY_RAG_ENABLED` off) and only the eval extension turns it on.

## 1. Dependencies + ingest entry point
- [ ] Add `llama-index-vector-stores-qdrant` + `fastembed` to `pyproject.toml`.
- [ ] `scripts/ingest_library.py`: YAML exploder (one doc per symptom tree with
      `{appliance, symptom_key, safety}`) + `docs/library/` reader (md/txt/pdf);
      embedded Qdrant at `QDRANT_PATH`; idempotent re-ingest (stable doc ids).
- [ ] `make ingest` target (`$(BIN)python scripts/ingest_library.py`).

## 2. Store module
- [ ] `app/knowledge/library_store.py`: embedded client, collection
      `appliance_library`, FastEmbed embedding config, `retrieve(query, k=3)`
      returning scored nodes with metadata; injectable fake for tests.

## 3. Tool + prompt wiring                              ⏸ review after this group
- [ ] `app/tools/library_tools.py`: `search_appliance_library(query) -> str`
      (auto-discovered; returns attributed summaries; registers only when
      `LIBRARY_RAG_ENABLED` is truthy so flag-off is byte-equivalent).
- [ ] One system-prompt guidance line (flag-conditional): use the library tool when
      the keyed lookup has no matching tree; never instead of the safety interrupt.

## 4. Eval extension
- [ ] Two scenarios in `evals/scenarios/library/`: out-of-tree query answered with
      cited library content; safety-adjacent query still routes to the interrupt.
- [ ] One retrieval canary (deliberately irrelevant corpus hit must fail the rubric).

## 5. Gates
- [ ] pytest: ingest idempotency (same point count on re-run), retrieval smoke
      asserting the three spike queries' top-1 hits, tool unit with fake store,
      flag-off equivalence test.
- [ ] `make lint` + `make test` + `make transcript` clean; `make ingest` runs clean.
- [ ] Tick roadmap Phase 6 `[x]` only when all of the above are green with the flag on.

## Integration deltas
- Compose: `qdrant_data` named volume mounted at `/app/data/qdrant` on the `app`
  service (same pattern as `uploads`); `.env.example` gains `LIBRARY_RAG_ENABLED`,
  `QDRANT_PATH`, `EMBED_MODEL`.
- Hardened Dockerfile must include the FastEmbed model cache or accept the one-time
  download on first ingest (document in README known limitations).
