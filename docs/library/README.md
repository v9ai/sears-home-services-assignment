# Appliance library corpus (`docs/library/`)

This folder is the extensible half of the appliance-library RAG corpus
(`2026-07-08-appliance-library-qdrant/requirements.md` → Included). `make ingest`
(`scripts/ingest_library.py`) reads every `.md` / `.txt` / `.pdf` file here via
LlamaIndex readers and indexes it into the embedded Qdrant `appliance_library`
collection alongside the six `app/knowledge/*.yaml` decision trees.

**No scraped or copyrighted manufacturer manuals are committed here** (Decision 5) —
that's a licensing posture for a take-home assignment, not a technical limitation.
`general_maintenance_tips.md` is the brand-agnostic starter document: short, original,
generically-worded appliance care guidance (not sourced from any Sears/Kenmore
document), included so the ingest pipeline and the "out-of-tree query answered with
cited library content" eval scenario have something real to retrieve.

`brands/` holds one brand-tagged guide per Sears store brand (Kenmore, Whirlpool,
GE, Samsung, LG, Maytag, Frigidaire, Bosch, Electrolux, KitchenAid, Amana) — the
Decision 7 scope. Each is original brand-oriented care/service background (rating
plate locations, error-code conventions, routine care), tagged via `brand:`
frontmatter so retrieval hits carry brand attribution; none of it is scraped manual
content, and none of it overrides the safety interrupt or the deterministic trees.

To extend this corpus for a real deployment, drop in Sears/Kenmore-licensed manuals
or guides (md/txt/pdf) and re-run `make ingest` — the loader picks up new files
automatically; no code changes required.

If a guide is specific to one brand/unit, tag it with a leading frontmatter block —
stripped from the indexed text and attributed on the resulting Qdrant point as
`brand`/`model_number` (`2026-07-08-appliance-library-qdrant/requirements.md`
Decision 7):

```
---
brand: Kenmore
model_number: 665.13743K310
---
Guide text starts here...
```

Both keys are optional and free-text (no fixed brand list) — omit the block entirely
for brand-agnostic guides like `general_maintenance_tips.md`. The `brands/*.md`
guides set `brand:` only; `model_number:` is for unit-specific documents.
