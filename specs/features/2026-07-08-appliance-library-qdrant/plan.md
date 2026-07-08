# Appliance Library RAG via Local Qdrant — Plan

Flag-gated and additive; implement in dependency order. The feature ships dark
(`LIBRARY_RAG_ENABLED` off) and only the eval extension turns it on.

## 1. Dependencies + ingest entry point
- [x] Add `llama-index-vector-stores-qdrant` + `fastembed` to `pyproject.toml`.
- [x] `scripts/ingest_library.py`: YAML exploder (one doc per symptom tree with
      `{appliance, symptom_key, safety}`) + `docs/library/` reader (md/txt/pdf);
      embedded Qdrant at `QDRANT_PATH`; idempotent re-ingest (stable doc ids).
- [x] `make ingest` target (`$(BIN)python scripts/ingest_library.py`).

## 2. Store module
- [x] `app/knowledge/library_store.py`: embedded client, collection
      `appliance_library`, FastEmbed embedding config, `retrieve(query, k=3)`
      returning scored nodes with metadata; injectable fake for tests.

## 3. Tool + prompt wiring                              ⏸ review after this group
- [x] `app/tools/library_tools.py`: `search_appliance_library(query) -> str`
      (auto-discovered; returns attributed summaries; registers only when
      `LIBRARY_RAG_ENABLED` is truthy so flag-off is byte-equivalent).
- [x] One system-prompt guidance line (flag-conditional): use the library tool when
      the keyed lookup has no matching tree; never instead of the safety interrupt.
      **Not applied to `app/agent/prompts.py`** — that file is owned by
      voice-diagnostic-core (COORDINATION.md §3); the exact line is recorded under
      Integration deltas below for the lead to apply.

## 4. Eval extension (LlamaIndex-native retrieval gate)
- [x] `DatasetGenerator` (judging on `get_llm()`/DeepSeek) builds the question→node
      dataset from the ingested knowledge docs; `RetrieverEvaluator` gates the Qdrant
      retriever at hit-rate ≥ 0.9 / MRR ≥ 0.7 (requirements Decision 6).
      Lives at `evals/test_library_retrieval.py`, inheriting `evals/conftest.py`'s
      existing skip-without-judge-key posture (question generation needs a live
      `get_llm()` call). Not independently verified live in this environment (no
      `DEEPSEEK_API_KEY` available) — verified instead via API-signature inspection
      against the installed `llama-index-core==0.14.23` plus a live dry run of the
      non-LLM retrieval/canary path against the real ingested index.
- [x] Two scenarios in `evals/scenarios/library/`: out-of-tree query answered with
      cited library content; safety-adjacent query still routes to the interrupt.
      **Schema note:** both use `feature: core` (not a new `feature: library` value)
      — `evals/scenarios/schema.py` and `tests/test_scenario_schema.py` are owned by
      testing-evals and the latter hard-asserts an exact `{"core", "scheduling",
      "visual"}` feature set plus an exact canary count, so adding a new enum value
      or a dedicated groundedness rubric isn't possible without editing files this
      feature doesn't own. `requires: [library]` is recorded on both scenarios as a
      documented (currently-unenforced) hint. See Integration deltas for the
      optional forward-looking schema extension.
- [x] One retrieval canary (deliberately irrelevant corpus hit must fail the rubric)
      — implemented as a LlamaIndex-native retrieval-layer canary (an off-corpus
      query scoring well below any real appliance-relevant match) in
      `evals/test_library_retrieval.py`, per Decision 6's reframing of the retrieval
      gate around `RetrieverEvaluator` rather than a DeepEval scenario canary (which
      would have hit the same schema-ownership constraint as above, since
      `RubricName`/canary-count are hard-checked too).

## 5. Gates
- [x] pytest: ingest idempotency (same point count on re-run), retrieval smoke
      asserting the three spike queries' top-1 hits, tool unit with fake store,
      flag-off equivalence test. (`tests/test_ingest_library.py`,
      `tests/test_library_tools.py`, `tests/test_library_flag.py`.)
- [x] `make lint` + `make test` + `make transcript` clean; `make ingest` runs clean.
      (`make test` requires a reachable `DATABASE_URL` for the pre-existing
      scheduling suite, same as before this feature — unrelated to this change.)
- [x] Tick roadmap Phase 6 `[x]` — all of the above green with the flag on;
      `make eval` correctly SKIPs (not fails) without a judge key, matching the
      documented posture for the rest of the DeepEval gate.

## Integration deltas

Everything below is a change to a file this feature doesn't own (COORDINATION.md §3)
— declared here, not made, per §3's "shared-file changes ... are declared, not made."

### 1. `docker-compose.yml` (owned by deployment-deliverables)
- Add a `qdrant_data` named volume, mounted at `/app/data/qdrant` on the `app`
  service (same pattern as the existing `uploads` volume), so the embedded Qdrant
  index persists across container restarts:
  ```yaml
  services:
    app:
      volumes:
        - uploads:/app/data/uploads
        - qdrant_data:/app/data/qdrant   # + this line
  volumes:
    pgdata:
    uploads:
    qdrant_data:   # + this line
  ```
- Hardened Dockerfile should pre-warm the FastEmbed model cache (`BAAI/bge-small-en-v1.5`,
  ~130 MB) at build time, or explicitly accept the one-time download on first
  `make ingest`/first tool call and document it in the README's known limitations —
  either is fine; whichever is chosen, the app container needs outbound network on
  first use if the cache isn't pre-warmed.

### 2. `.env.example` (contract file, mission non-negotiable 5)
Add, in the "Backend non-secret config" section:
```
# --- Appliance library RAG (Phase 6, optional, flag-gated — off by default) ---
# 1/true/yes/on enables `search_appliance_library`; anything else (incl. unset) keeps
# flag-off behavior byte-equivalent to today's agent. Run `make ingest` first.
LIBRARY_RAG_ENABLED=
# QDRANT_PATH=data/qdrant          (embedded Qdrant storage dir; Docker volume qdrant_data)
# EMBED_MODEL=BAAI/bge-small-en-v1.5   (FastEmbed, local, downloads once ~130MB)
```
`tech-stack.md`'s Secrets classification table should list `LIBRARY_RAG_ENABLED`,
`QDRANT_PATH`, `EMBED_MODEL` under "Backend non-secret config" alongside the existing
row (none of the three are secrets).

### 3. `app/agent/prompts.py` (owned by voice-diagnostic-core)
One flag-conditional guidance section, added the same way `IMAGE_UPLOAD_CONTRACT` is
— a new module-level string plus one appended section in `build_system_prompt`. Exact
proposed diff:
```diff
--- a/app/agent/prompts.py
+++ b/app/agent/prompts.py
@@
+LIBRARY_GUIDANCE = """Appliance library fallback: if `get_troubleshooting_steps` \
+reports no matching symptom_key for this appliance, call \
+`search_appliance_library(query)` for a fallback answer grounded in the appliance \
+library, and relay it citing its source — never invent troubleshooting steps \
+yourself, and never use this in place of the safety interrupt."""
+
+
 def _knowledge_vocabulary(case_file: CaseFile) -> str:
@@
 def build_system_prompt(case_file: CaseFile) -> str:
     """Compose the full system prompt for one turn, case file injected fresh each time."""
     case_file_json = case_file.model_dump_json(indent=2)
     sections = [
         PERSONA,
         NON_NEGOTIABLES,
         SCHEDULING_CONTRACT,
         IMAGE_UPLOAD_CONTRACT,
         _knowledge_vocabulary(case_file),
         f"Current case file (JSON) — do not ask again for anything already here:\n{case_file_json}",
     ]
+    if os.environ.get("LIBRARY_RAG_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
+        sections.append(LIBRARY_GUIDANCE)
     if case_file.safety_flag:
```
(needs `import os` added to the existing import block). The truthy-value set matches
`app/tools/library_tools.py::_flag_enabled()` exactly — keep them identical if either
changes.

### 4. `evals/scenarios/schema.py` + `tests/test_scenario_schema.py` (owned by testing-evals) — optional, forward-looking
Not required for this feature to ship (the two hand-authored scenarios in
`evals/scenarios/library/` validate today using `feature: core` — see plan.md group
4). If a future pass wants a first-class `feature: library` + a dedicated
groundedness/citation rubric instead of the `core` workaround:
- `Feature = Literal["core", "scheduling", "visual", "library"]`
- `RubricName` gains e.g. `"library_groundedness"` (+ a matching
  `RUBRIC_METRICS["library_groundedness"]` G-Eval rubric in `evals/metrics.py`,
  also not owned by this feature)
- `tests/test_scenario_schema.py::test_matrix_covers_core_scheduling_visual` needs
  its hardcoded `{"core", "scheduling", "visual"}` equality widened accordingly.

### 5. Roadmap / constitution
- `specs/constitution/roadmap.md` Phase 6 checkbox ticked `[x]` in this commit (a
  single-line change scoped entirely to this feature's own phase entry, not a
  cross-feature edit).
- `specs/constitution/tech-stack.md`'s forbidden-pattern carve-out for this feature
  was already amended in a prior commit (`fac33da`); no further tech-stack.md change
  needed by this feature.

### 6. Local dev environment note (not a code delta)
This worktree had no `.venv` at task start (sibling feature worktrees each had their
own); one was created (`python3.12 -m venv .venv && pip install -e ".[dev]"`,
gitignored) so `make ingest`/`make lint`/`make test` run exactly as a reviewer would
run them. No repo file depends on this — noted only so the lead isn't surprised by an
untracked `.venv/` in this worktree's working directory (already covered by
`.gitignore`).
