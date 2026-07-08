"""Tool unit tests for `search_appliance_library` (plan.md group 5) — driven entirely
against the injectable fake store (COORDINATION.md §4 stub seam), never a real Qdrant
client or embedding model.
"""

from __future__ import annotations

import pytest

from app.knowledge import library_store
from app.knowledge.library_store import LibraryHit
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
