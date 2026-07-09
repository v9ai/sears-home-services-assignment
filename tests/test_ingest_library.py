"""`scripts/ingest_library.py` gates (plan.md group 5 / validation.md):

- idempotency: two consecutive `make ingest`-equivalent runs produce the same point
  count in the `appliance_library` collection;
- retrieval smoke: the three spike queries pinned in requirements.md's feasibility
  table return the expected top-1 hit (real embedded Qdrant + real FastEmbed model —
  not the fake store; this is the one test that exercises the real pipeline
  end-to-end, per validation.md).

Each embedded `QdrantClient(path=...)` locks its storage directory for as long as the
client is open, so every run here uses a *subprocess* (a fresh process, its own
client, closed on exit) rather than importing `ingest()` in-process repeatedly against
the same path.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INGEST_SCRIPT = REPO_ROOT / "scripts" / "ingest_library.py"


def _run_ingest(qdrant_path: Path) -> None:
    env = dict(os.environ)
    env["QDRANT_PATH"] = str(qdrant_path)
    result = subprocess.run(
        [sys.executable, str(INGEST_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"ingest failed (exit {result.returncode})\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


def _point_count(qdrant_path: Path) -> int:
    from qdrant_client import QdrantClient

    client = QdrantClient(path=str(qdrant_path))
    try:
        return client.count("appliance_library").count
    finally:
        client.close()


@pytest.fixture(scope="module")
def ingested_index(tmp_path_factory: pytest.TempPathFactory) -> Path:
    qdrant_path = tmp_path_factory.mktemp("qdrant_ingest_gate")
    _run_ingest(qdrant_path)
    return qdrant_path


def test_ingest_is_idempotent(tmp_path: Path) -> None:
    _run_ingest(tmp_path)
    first_count = _point_count(tmp_path)

    _run_ingest(tmp_path)
    second_count = _point_count(tmp_path)

    assert first_count > 0
    assert first_count == second_count


def test_ingest_covers_all_24_yaml_symptom_trees_plus_docs_library(
    ingested_index: Path,
) -> None:
    # 6 appliances x >=3 symptom trees each = >=18; the repo's actual trees total 24
    # (requirements.md feasibility table). Plus docs/library/general_maintenance_tips.md.
    count = _point_count(ingested_index)
    assert count >= 24 + 1


@pytest.mark.parametrize(
    ("query", "expected_appliance", "expected_symptom_key", "expect_safety"),
    [
        ("washing machine loud grinding noise", "washer", "loud_noise", False),
        ("smell gas when I turn on the oven", "oven", "safety_gas_smell", True),
        ("fridge not cold since yesterday", "refrigerator", "not_cooling", False),
    ],
)
def test_retrieval_smoke_matches_pinned_spike_queries(
    ingested_index: Path,
    query: str,
    expected_appliance: str,
    expected_symptom_key: str,
    expect_safety: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QDRANT_PATH", str(ingested_index))
    from app.knowledge.library_store import QdrantLibraryStore

    store = QdrantLibraryStore(path=str(ingested_index))
    hits = store.retrieve(query, k=3)

    assert hits, f"no hits for query {query!r}"
    top = hits[0]
    assert top.appliance == expected_appliance
    assert top.symptom_key == expected_symptom_key
    assert top.safety is expect_safety


ALL_BRANDS = [
    "Amana",
    "Bosch",
    "Electrolux",
    "Frigidaire",
    "GE",
    "Kenmore",
    "KitchenAid",
    "LG",
    "Maytag",
    "Samsung",
    "Whirlpool",
]


@pytest.mark.parametrize("brand", ALL_BRANDS)
def test_every_brand_doc_is_retrievable_with_brand_metadata(
    ingested_index: Path, brand: str
) -> None:
    # docs/library/brands/*.md — one brand-tagged guide per Sears store brand,
    # `brand:` set via frontmatter (Decision 7), frontmatter stripped from the text.
    # A brand-named query must disambiguate to that brand's own guide top-1.
    from app.knowledge.library_store import QdrantLibraryStore

    store = QdrantLibraryStore(path=str(ingested_index))
    hits = store.retrieve(f"{brand} appliance care and service notes for my {brand} unit", k=3)

    assert hits, f"no hits for brand query {brand!r}"
    top = hits[0]
    assert top.brand == brand
    assert top.source == f"docs/library/brands/{brand.lower()}.md"
    assert "brand:" not in top.text.lower()


def test_yaml_docs_always_carry_null_brand_and_model_number(ingested_index: Path) -> None:
    from app.knowledge.library_store import QdrantLibraryStore

    store = QdrantLibraryStore(path=str(ingested_index))
    hits = store.retrieve("washing machine loud grinding noise", k=1)

    assert hits
    assert hits[0].brand is None
    assert hits[0].model_number is None


def test_docs_library_frontmatter_sets_brand_and_model_number(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs_library"
    docs_dir.mkdir()
    (docs_dir / "kenmore_dishwasher_665.md").write_text(
        "---\n"
        "brand: Kenmore\n"
        "model_number: 665.13743K310\n"
        "---\n"
        "If the control panel shows error code PF, check for a recent power outage "
        "and simply restart the cycle once power is confirmed stable.\n"
    )
    qdrant_path = tmp_path / "qdrant"
    env = dict(os.environ)
    env["QDRANT_PATH"] = str(qdrant_path)
    env["LIBRARY_DOCS_DIR"] = str(docs_dir)
    result = subprocess.run(
        [sys.executable, str(INGEST_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"ingest failed (exit {result.returncode})\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    from app.knowledge.library_store import QdrantLibraryStore

    store = QdrantLibraryStore(path=str(qdrant_path))
    hits = store.retrieve("dishwasher control panel shows error code PF", k=1)

    assert hits
    top = hits[0]
    assert top.brand == "Kenmore"
    assert top.model_number == "665.13743K310"
    assert "brand:" not in top.text.lower()
    assert "model_number:" not in top.text.lower()
