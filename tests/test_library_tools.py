"""Tool unit tests for `search_appliance_library` (plan.md group 5) — driven entirely
against the injectable fake store (COORDINATION.md §4 stub seam), never a real Qdrant
client or embedding model.
"""

from __future__ import annotations

import logging

import pytest

from app.knowledge import library_store
from app.knowledge.library_store import LibraryHit
from app.tools import library_tools
from app.tools.library_tools import search_appliance_library


class FakeLibraryStore:
    """Scripted stand-in for `QdrantLibraryStore`: returns canned hits in order."""

    def __init__(self, hits: list[LibraryHit]) -> None:
        self._hits = hits
        self.last_query: str | None = None
        self.last_k: int | None = None

    def retrieve(self, query: str, k: int = 3) -> list[LibraryHit]:
        self.last_query = query
        self.last_k = k
        return self._hits[:k]


@pytest.fixture(autouse=True)
def _reset_store():
    library_store.set_store(None)
    yield
    library_store.set_store(None)


async def test_no_hits_returns_a_plain_no_results_message() -> None:
    library_store.set_store(FakeLibraryStore([]))
    result = await search_appliance_library("a query with no matches")
    assert "No relevant entries" in result


async def test_attributed_summary_includes_appliance_and_symptom_key() -> None:
    hits = [
        LibraryHit(
            text="Check for coins or small items caught in the drum.",
            score=0.845,
            appliance="washer",
            symptom_key="loud_noise",
            source="app/knowledge/washer.yaml#loud_noise",
            safety=False,
        )
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("washing machine loud grinding noise")
    assert "washer/loud_noise" in result
    assert "app/knowledge/washer.yaml#loud_noise" in result
    assert "0.85" in result or "0.84" in result
    assert "SAFETY" not in result


async def test_safety_hit_gets_a_callout() -> None:
    hits = [
        LibraryHit(
            text="Turn off the gas supply at the shutoff valve.",
            score=0.819,
            appliance="oven",
            symptom_key="safety_gas_smell",
            source="app/knowledge/oven.yaml#safety_gas_smell",
            safety=True,
        )
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("smell gas when I turn on the oven")
    assert "SAFETY" in result
    assert "escalate" in result.lower()


async def test_hit_with_brand_and_model_number_includes_unit_in_label() -> None:
    hits = [
        LibraryHit(
            text="If the control panel shows error code PF, restart the cycle.",
            score=0.81,
            appliance=None,
            symptom_key=None,
            source="docs/library/kenmore_dishwasher_665.md",
            safety=False,
            brand="Kenmore",
            model_number="665.13743K310",
        )
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("dishwasher shows error code PF")
    assert "(Kenmore 665.13743K310)" in result


async def test_docs_library_hit_uses_source_as_label_when_no_symptom_key() -> None:
    hits = [
        LibraryHit(
            text="Clean the dryer's exterior vent duct at least once a year.",
            score=0.75,
            appliance=None,
            symptom_key=None,
            source="docs/library/general_maintenance_tips.md",
            safety=False,
        )
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("how often should I clean my dryer vent")
    assert "docs/library/general_maintenance_tips.md" in result


async def test_k_limit_is_respected_via_the_fake_store() -> None:
    hits = [
        LibraryHit(
            text=f"entry {i}",
            score=0.9 - i * 0.05,
            appliance="washer",
            symptom_key=f"key_{i}",
            source=f"app/knowledge/washer.yaml#key_{i}",
            safety=False,
        )
        for i in range(5)
    ]
    fake = FakeLibraryStore(hits)
    library_store.set_store(fake)
    result = await search_appliance_library("some query")
    assert fake.last_k == 3
    assert result.count("app/knowledge/washer.yaml#key_") == 3


async def test_query_is_forwarded_to_the_store_unmodified() -> None:
    fake = FakeLibraryStore([])
    library_store.set_store(fake)
    await search_appliance_library("fridge not cold since yesterday")
    assert fake.last_query == "fridge not cold since yesterday"


async def test_multiple_hits_are_numbered_in_order() -> None:
    hits = [
        LibraryHit(
            text=f"entry {i}",
            score=0.9 - i * 0.1,
            appliance="washer",
            symptom_key=f"key_{i}",
            source=f"app/knowledge/washer.yaml#key_{i}",
            safety=False,
        )
        for i in range(3)
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("washer trouble")
    assert "1. [washer/key_0]" in result
    assert "2. [washer/key_1]" in result
    assert "3. [washer/key_2]" in result
    assert result.index("key_0") < result.index("key_1") < result.index("key_2")


async def test_long_snippet_is_truncated_with_ellipsis() -> None:
    long_text = "x" * 900
    hits = [
        LibraryHit(
            text=long_text,
            score=0.7,
            appliance="dryer",
            symptom_key="no_heat",
            source="app/knowledge/dryer.yaml#no_heat",
            safety=False,
        )
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("dryer no heat")
    assert "..." in result
    # The snippet body is capped near 400 chars — the full 900-char text is not emitted.
    assert long_text not in result


async def test_newlines_in_hit_text_are_collapsed_to_spaces() -> None:
    hits = [
        LibraryHit(
            text="line one\nline two\nline three",
            score=0.7,
            appliance="oven",
            symptom_key="wont_heat",
            source="app/knowledge/oven.yaml#wont_heat",
            safety=False,
        )
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("oven won't heat")
    assert "line one line two line three" in result


async def test_score_is_formatted_to_two_decimals() -> None:
    hits = [
        LibraryHit(
            text="entry",
            score=0.833333,
            appliance="washer",
            symptom_key="loud_noise",
            source="app/knowledge/washer.yaml#loud_noise",
            safety=False,
        )
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("noise")
    assert "score 0.83" in result


async def test_brand_only_hit_labels_the_brand_without_a_model() -> None:
    hits = [
        LibraryHit(
            text="Whirlpool care notes.",
            score=0.8,
            appliance=None,
            symptom_key=None,
            source="docs/library/brands/whirlpool.md",
            safety=False,
            brand="Whirlpool",
            model_number=None,
        )
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("whirlpool care")
    assert "(Whirlpool)" in result


async def test_model_only_hit_labels_the_model_without_a_brand() -> None:
    hits = [
        LibraryHit(
            text="Model-specific reset steps.",
            score=0.8,
            appliance=None,
            symptom_key=None,
            source="docs/library/some_model.md",
            safety=False,
            brand=None,
            model_number="ABC-123",
        )
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("reset steps")
    assert "(ABC-123)" in result


async def test_results_always_carry_the_cite_the_source_header() -> None:
    hits = [
        LibraryHit(
            text="something",
            score=0.7,
            appliance="washer",
            symptom_key="loud_noise",
            source="app/knowledge/washer.yaml#loud_noise",
            safety=False,
        )
    ]
    library_store.set_store(FakeLibraryStore(hits))
    result = await search_appliance_library("noise")
    assert "cite the source" in result.lower()


class _MissingCollectionStore:
    """Simulates a flag-on-before-ingest deploy: the Qdrant collection is absent, so
    retrieve() raises exactly as QdrantVectorStore does (task #17 repro)."""

    def retrieve(self, query: str, k: int = 3):
        raise ValueError("Collection appliance_library not found")


async def test_missing_index_degrades_gracefully_instead_of_crashing(caplog) -> None:
    # Regression for task #17: this tool is advisory augmentation only, so a retrieval
    # failure (canonically LIBRARY_RAG_ENABLED flipped on before `make ingest`) must
    # degrade to the no-results message rather than propagate into the agent's tool loop
    # and break a live turn.
    library_tools._degraded_logged = False  # let the one-time degraded log fire here
    library_store.set_store(_MissingCollectionStore())
    with caplog.at_level(logging.INFO, logger="app.tools.library"):
        result = await search_appliance_library("washer won't drain")
    assert "No relevant entries" in result
    assert "library.rag.retrieve_degraded" in caplog.text


async def test_missing_index_degraded_event_is_logged_only_once(caplog) -> None:
    # The misconfig must surface once per process, not on every agent turn.
    library_tools._degraded_logged = False
    library_store.set_store(_MissingCollectionStore())
    with caplog.at_level(logging.INFO, logger="app.tools.library"):
        await search_appliance_library("first query")
        assert "library.rag.retrieve_degraded" in caplog.text
        caplog.clear()
        await search_appliance_library("second query")
        assert "library.rag.retrieve_degraded" not in caplog.text
