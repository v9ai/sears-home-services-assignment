# Appliance library corpus (`docs/library/`)

This folder is the extensible half of the appliance-library RAG corpus
(`2026-07-08-appliance-library-qdrant/requirements.md` → Included). `make ingest`
(`scripts/ingest_library.py`) reads every `.md` / `.txt` / `.pdf` file here via
LlamaIndex readers and indexes it into the embedded Qdrant `appliance_library`
collection alongside the six `app/knowledge/*.yaml` decision trees.

**No scraped or copyrighted manufacturer manuals are committed here** (Decision 5) —
that's a licensing posture for a take-home assignment, not a technical limitation.
`general_maintenance_tips.md` is the one starter document: short, original,
generically-worded appliance care guidance (not sourced from any Sears/Kenmore
document), included so the ingest pipeline and the "out-of-tree query answered with
cited library content" eval scenario have something real to retrieve.

To extend this corpus for a real deployment, drop in Sears/Kenmore-licensed manuals
or guides (md/txt/pdf) and re-run `make ingest` — the loader picks up new files
automatically; no code changes required.
