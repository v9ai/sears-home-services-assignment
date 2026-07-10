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


# --- Hermetic document-building unit tests (no Qdrant, no embedding model) -----------
#
# The subprocess tests above exercise the real embedded-Qdrant pipeline end to end.
# These import the ingest module's pure functions directly so the corpus/metadata/
# frontmatter/idempotency logic is pinned in milliseconds, independent of any index.

from scripts import ingest_library  # noqa: E402
from scripts.ingest_library import (  # noqa: E402
    _extract_frontmatter,
    _stable_id,
    _symptom_tree_text,
    build_documents,
    library_docs_documents,
    yaml_documents,
)


def test_extract_frontmatter_parses_leading_block_and_strips_it() -> None:
    front, body = _extract_frontmatter(
        "---\nbrand: LG\nmodel_number: WM3600\n---\nActual guidance text here.\n"
    )
    assert front == {"brand": "LG", "model_number": "WM3600"}
    assert body.strip() == "Actual guidance text here."
    assert "brand:" not in body


def test_extract_frontmatter_absent_block_returns_text_unchanged() -> None:
    text = "No frontmatter, just body.\nSecond line.\n"
    front, body = _extract_frontmatter(text)
    assert front == {}
    assert body == text


def test_extract_frontmatter_empty_block_yields_empty_mapping() -> None:
    front, body = _extract_frontmatter("---\n\n---\nBody after empty block.\n")
    assert front == {}
    assert body.strip() == "Body after empty block."


def test_extract_frontmatter_only_when_block_is_at_the_very_start() -> None:
    # A '---' that is not the first thing in the file is NOT frontmatter.
    text = "Intro line.\n---\nbrand: LG\n---\n"
    front, body = _extract_frontmatter(text)
    assert front == {}
    assert body == text


def test_stable_id_is_deterministic_and_input_sensitive() -> None:
    assert _stable_id("yaml", "washer", "loud_noise") == _stable_id("yaml", "washer", "loud_noise")
    assert _stable_id("yaml", "washer", "loud_noise") != _stable_id("yaml", "washer", "not_cooling")
    # Component boundaries matter — the joiner must prevent collisions across splits.
    assert _stable_id("a", "bc") != _stable_id("ab", "c")


def test_symptom_tree_text_includes_all_present_sections() -> None:
    text = _symptom_tree_text(
        "washer",
        "loud_noise",
        {"questions": ["Any coins?"], "steps": ["Check the drum."], "escalate_if": "grinding"},
    )
    assert "Appliance: washer" in text
    assert "Symptom: loud_noise" in text
    assert "Clarifying questions: Any coins?" in text
    assert "Steps: Check the drum." in text
    assert "Escalate if: grinding" in text


def test_symptom_tree_text_omits_absent_optional_sections() -> None:
    text = _symptom_tree_text("dryer", "no_heat", {"steps": ["Check the breaker."]})
    assert "Clarifying questions:" not in text
    assert "Escalate if:" not in text
    assert "Steps: Check the breaker." in text


def test_yaml_documents_cover_every_symptom_tree_once() -> None:
    from app.knowledge.loader import ALL_APPLIANCES, load_knowledge

    docs = yaml_documents()
    expected = sum(len(load_knowledge(a).symptoms) for a in ALL_APPLIANCES)
    assert len(docs) == expected
    # One document per (appliance, symptom_key), no duplicates.
    pairs = [(d.metadata["appliance"], d.metadata["symptom_key"]) for d in docs]
    assert len(pairs) == len(set(pairs))


def test_yaml_documents_metadata_shape_and_safety_derivation() -> None:
    for doc in yaml_documents():
        meta = doc.metadata
        assert meta["appliance"] is not None
        assert meta["symptom_key"] is not None
        assert meta["source"] == f"app/knowledge/{meta['appliance']}.yaml#{meta['symptom_key']}"
        # Brand-agnostic by design (Decision 5): YAML docs always null brand/model.
        assert meta["brand"] is None
        assert meta["model_number"] is None
        # safety flag is derived purely from the symptom_key prefix.
        assert meta["safety"] == meta["symptom_key"].startswith("safety_")


def test_yaml_documents_are_reproducible_across_calls() -> None:
    # Idempotency at the document level: same ids, text, and metadata every build.
    first = {d.doc_id: (d.text, tuple(sorted(d.metadata.items()))) for d in yaml_documents()}
    second = {d.doc_id: (d.text, tuple(sorted(d.metadata.items()))) for d in yaml_documents()}
    assert first == second


def test_library_docs_documents_reads_frontmatter_and_strips_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs_dir = tmp_path / "lib"
    docs_dir.mkdir()
    (docs_dir / "acme_guide.md").write_text(
        "---\nbrand: Acme\nmodel_number: X-1\n---\nKeep the vent clear and dry.\n"
    )
    (docs_dir / "README.md").write_text("should be excluded\n")
    monkeypatch.setattr(ingest_library, "LIBRARY_DOCS_DIR", docs_dir)

    docs = library_docs_documents()
    assert len(docs) == 1  # README.md excluded
    doc = docs[0]
    assert doc.metadata["brand"] == "Acme"
    assert doc.metadata["model_number"] == "X-1"
    assert doc.metadata["appliance"] is None
    assert doc.metadata["symptom_key"] is None
    assert doc.metadata["safety"] is False
    assert doc.metadata["source"].endswith("acme_guide.md")
    assert "brand:" not in doc.text.lower()
    assert "Keep the vent clear" in doc.text


def test_library_docs_documents_empty_when_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest_library, "LIBRARY_DOCS_DIR", tmp_path / "nonexistent")
    assert library_docs_documents() == []


def test_library_docs_documents_null_brand_when_no_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs_dir = tmp_path / "lib"
    docs_dir.mkdir()
    (docs_dir / "plain_tips.md").write_text("Vacuum the condenser coils twice a year.\n")
    monkeypatch.setattr(ingest_library, "LIBRARY_DOCS_DIR", docs_dir)

    docs = library_docs_documents()
    assert len(docs) == 1
    assert docs[0].metadata["brand"] is None
    assert docs[0].metadata["model_number"] is None


def test_build_documents_is_yaml_plus_docs_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest_library, "LIBRARY_DOCS_DIR", tmp_path / "empty_missing")
    combined = build_documents()
    assert len(combined) == len(yaml_documents()) + len(library_docs_documents())
