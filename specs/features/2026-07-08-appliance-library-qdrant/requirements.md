# Appliance Library RAG via Local Qdrant — Requirements

## Source
User directive (2026-07-08):
> check if possible to ingest locally via qdrant a library of appliances related to
> this company, create spec if possible

Promotes the roadmap backlog item "RAG over manufacturer service manuals" into a
specified, **flag-gated, augmentation-only** feature. Constitution-revising: the
`tech-stack.md` forbidden pattern gains a carve-out (amended in the same commit).

## Feasibility (spike-verified 2026-07-08, scratchpad only — no repo code)

| Aspect | Result |
|---|---|
| Vector store | **Embedded Qdrant** (`QdrantClient(path=...)`) — fully local, on-disk, no server/Compose service, via `llama-index-vector-stores-qdrant` |
| Embeddings | **FastEmbed** `BAAI/bge-small-en-v1.5` (ONNX, CPU) — local, zero API cost, offline |
| Corpus | The six `app/knowledge/*.yaml` files exploded into **24 symptom-tree documents** with `{appliance, symptom_key, safety}` metadata |
| Ingest | 1.5 s (embed + index, on-disk) |
| Retrieval | 3 queries in 18 ms total |
| Quality | "washing machine loud grinding noise" → `washer/loud_noise` 0.845 · "smell gas when I turn on the oven" → `oven/safety_gas_smell` **[SAFETY]** 0.819 · "fridge not cold since yesterday" → `refrigerator/not_cooling` 0.736 |
| Caveat | Embedded mode has no payload indexes (warning observed) — irrelevant at this scale; Qdrant server via Compose is the recorded scale-up path |

## Scope

### Included
- `make ingest` → `scripts/ingest_library.py`: builds the local index from
  (a) the six knowledge YAMLs — one document per symptom tree, metadata
  `{appliance, symptom_key, safety: bool}` — and (b) an extensible `docs/library/`
  folder for appliance manuals/guides (md/txt/pdf via LlamaIndex readers,
  Sears/Kenmore-oriented). Idempotent: re-running re-ingests to the same point count.
- Embedded Qdrant persisted at `QDRANT_PATH` (default `data/qdrant/` — a Docker named
  volume `qdrant_data`, consistent with the Docker-volume storage decision).
- Store module `app/knowledge/library_store.py` (embedded client, collection
  `appliance_library`, LlamaIndex `VectorStoreIndex` retriever).
- New auto-discovered tool `search_appliance_library(query) → str`
  (`app/tools/library_tools.py`): top-k results summarized with appliance +
  symptom_key/source + safety attribution; called by the agent when the keyed
  `get_troubleshooting_steps` lookup has no matching tree.
- Feature flag `LIBRARY_RAG_ENABLED` (default **off**): flag-off behavior is
  byte-equivalent to today's agent.

### Not included (deferred)
- Replacing the deterministic YAML trees — they stay the **primary** diagnostic path;
  retrieval is fallback/augmentation only.
- Qdrant server mode (Compose `qdrant` service) — recorded scale-up path once the
  corpus outgrows embedded mode or payload indexes are needed.
- Re-ranking, hybrid/BM25 search, cloud vector stores, embedding-model tuning.

### Contract shapes
- Document metadata: `{appliance: str|null, symptom_key: str|null, source: str,
  safety: bool}` (YAML-derived docs carry appliance/symptom_key; `docs/library/`
  passages carry source path).
- Tool signature (frozen-contract addition, COORDINATION §2):
  `search_appliance_library(query: str) -> str`.
- Env: `LIBRARY_RAG_ENABLED` (default unset/off), `QDRANT_PATH=data/qdrant`,
  `EMBED_MODEL=BAAI/bge-small-en-v1.5`.
- Deps: `llama-index-vector-stores-qdrant`, `fastembed` (pulls `qdrant-client`).
- Pipeline: `make ingest` · gates `make lint`, `make test`, `make transcript` + the
  eval extension below.

## Decisions
1. **Embedded Qdrant over a server** — zero infra, works inside the existing `app`
   container and offline (mission non-negotiable 3); the payload-index limitation is
   recorded and irrelevant at ~10²–10³ documents. Server mode is the scale-up path,
   not the default.
2. **FastEmbed local embeddings over OpenAI embeddings** — no API cost (assignment §7
   cost posture), no key needed for ingest/retrieval, deterministic offline demo. The
   model downloads once (~130 MB) at first ingest.
3. **Augmentation, not replacement** — the deterministic trees remain authoritative;
   the safety interrupt runs as a pre-filter *before* any retrieval, so mission
   non-negotiable 1 is structurally unaffected. Retrieval results are advisory
   context, exactly like the vision analysis (visual-diagnosis Decision 2 precedent).
4. **Flag default off** — stays off until the eval extension (retrieval scenarios +
   canary) is green; flag-off is byte-equivalent, so shipping the code is risk-free.
5. **Corpus seeding strategy** — start from the repo's own YAML trees (already
   curated, safety-annotated) plus `docs/library/`; no scraped manufacturer content
   lands in the repo (licensing posture for a take-home).

## Architecture impact
- **Constitution-revising**: `tech-stack.md`'s "no vector DB / embeddings" forbidden
  pattern is amended to a primary-path prohibition with this feature as the sole
  sanctioned, flag-gated exception; `make ingest` + env/deps added; roadmap backlog
  item promoted to optional Phase 6. Amended in this commit per non-negotiable 6.

## Context
- Stack & conventions: `specs/constitution/tech-stack.md`; tool auto-discovery
  (`app/tools/registry.py`) means adding the tool = adding a file.
- Ownership (COORDINATION §3 addition): `app/tools/library_tools.py`,
  `app/knowledge/library_store.py`, `scripts/ingest_library.py`, `docs/library/`.
- Constraints: never bypass the safety pre-filter; `LIBRARY_RAG_ENABLED` off ⇒
  byte-equivalent behavior; no scraped copyrighted manuals committed.
- Open question (deferred): chunking policy for large PDFs in `docs/library/`
  (default LlamaIndex sentence splitter until evidence demands otherwise).
