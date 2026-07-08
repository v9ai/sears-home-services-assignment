"""Appliance-library RAG tool (Phase 6, flag-gated).

Auto-discovered by `app/tools/registry.py` via the module-level ``TOOLS`` list
(COORDINATION.md §1). Unlike every other tools module, ``TOOLS`` here is
conditional: it only contains `search_appliance_library` when `LIBRARY_RAG_ENABLED`
is truthy (requirements.md → Included: "flag-off behavior is byte-equivalent to
today's agent"). With the flag off, `TOOLS == []` and nothing in this module ever
touches Qdrant or FastEmbed — `app.knowledge.library_store` is only imported inside
the tool function body, not at module scope, so even the import doesn't download the
embedding model or open a Qdrant client when the flag is off.

This tool is retrieval-only augmentation: it never runs ahead of, or instead of, the
safety interrupt (`app/ws/routes.py` runs `detect_safety_trigger` on the raw caller
utterance *before* the agent's tool-calling loop is ever entered — this tool only
executes inside that loop, so it is structurally unable to bypass the pre-filter).
"""

from __future__ import annotations

import os


def _flag_enabled() -> bool:
    return os.environ.get("LIBRARY_RAG_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def search_appliance_library(query: str) -> str:
    """Search the appliance-library knowledge base for guidance outside the
    deterministic troubleshooting trees.

    Call this only after `get_troubleshooting_steps` reports an unknown
    `symptom_key` for the identified appliance (no matching deterministic tree) —
    never in place of it, and never in place of the safety interrupt. Results are
    advisory context grounded in the appliance library (the same knowledge trees
    plus any extended guides), each attributed to its source; relay them citing
    that source rather than inventing troubleshooting steps yourself. If a result
    is flagged as safety-related, treat it as an escalation script, not a DIY step,
    and offer to schedule a technician instead of continuing troubleshooting. Some
    results carry a brand/model number (e.g. from a brand-specific guide) — mention
    it only if the caller's own appliance matches; don't assume it applies otherwise.
    """
    from app.knowledge.library_store import retrieve

    hits = retrieve(query, k=3)
    if not hits:
        return "No relevant entries found in the appliance library for that query."

    lines = ["Appliance library results (cite the source when relaying these):"]
    for i, hit in enumerate(hits, start=1):
        label = (
            f"{hit.appliance}/{hit.symptom_key}"
            if hit.appliance and hit.symptom_key
            else hit.source
        )
        if hit.brand or hit.model_number:
            unit = " ".join(part for part in (hit.brand, hit.model_number) if part)
            label = f"{label} ({unit})"
        safety_note = " [SAFETY — escalate, do not continue DIY steps]" if hit.safety else ""
        snippet = hit.text.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400].rstrip() + "..."
        lines.append(
            f"{i}. [{label}] (source: {hit.source}, score {hit.score:.2f}){safety_note}\n"
            f"   {snippet}"
        )
    return "\n".join(lines)


TOOLS = [search_appliance_library] if _flag_enabled() else []
