#!/usr/bin/env python3
"""`make ingest` — build/rebuild the local embedded-Qdrant appliance-library index.

Corpus (requirements.md → Included):
  (a) the six `app/knowledge/*.yaml` decision trees, exploded one document per
      symptom tree, metadata `{appliance, symptom_key, source, safety}`;
  (b) an extensible `docs/library/` folder (md/txt/pdf via LlamaIndex readers) —
      Sears/Kenmore-oriented guides; deliberately near-empty in this repo (Decision 5:
      no scraped manufacturer manuals committed).

Idempotent (requirements.md → Included, validation.md): re-running drops and rebuilds
the `appliance_library` Qdrant collection from source, so two consecutive runs always
produce the same point count — simpler and just as correct as incremental upsert at
this corpus size (10^2-10^3 documents, per Decision 1's caveat).

Embedded Qdrant (`QdrantClient(path=...)`) locks its storage directory for the
lifetime of the client — this script owns exactly one client for its whole run and
closes it before exiting, so a second `python scripts/ingest_library.py` (a fresh
process) never collides with a still-open handle from the first.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import yaml
from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.knowledge.library_store import (  # noqa: E402
    COLLECTION_NAME,
    FastEmbedLocalEmbedding,
    embed_model_name,
    qdrant_path,
)
from app.knowledge.loader import ALL_APPLIANCES, KNOWLEDGE_DIR  # noqa: E402
from app.knowledge.schema import SAFETY_KEY_PREFIX  # noqa: E402

logger = logging.getLogger("ingest_library")

LIBRARY_DOCS_DIR = REPO_ROOT / "docs" / "library"
LIBRARY_DOC_SUFFIXES = {".md", ".txt", ".pdf"}


def _stable_id(*parts: str) -> str:
    """Deterministic doc id so re-ingesting is reproducible (not load-bearing for
    idempotency here, since the whole collection is rebuilt each run, but useful for
    citation/debugging and for any future move to incremental upsert)."""
    return hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()


def _symptom_tree_text(appliance: str, symptom_key: str, tree: dict) -> str:
    parts = [f"Appliance: {appliance}", f"Symptom: {symptom_key}"]
    questions = tree.get("questions") or []
    if questions:
        parts.append("Clarifying questions: " + " ".join(questions))
    steps = tree.get("steps") or []
    if steps:
        parts.append("Steps: " + " ".join(steps))
    escalate_if = tree.get("escalate_if")
    if escalate_if:
        parts.append(f"Escalate if: {escalate_if}")
    return "\n".join(parts)


def yaml_documents() -> list[Document]:
    """One document per symptom tree across the six knowledge YAMLs."""
    documents: list[Document] = []
    for appliance in ALL_APPLIANCES:
        path = KNOWLEDGE_DIR / f"{appliance}.yaml"
        if not path.exists():
            continue
        raw = yaml.safe_load(path.read_text()) or {}
        for symptom_key, tree in raw.items():
            is_safety = symptom_key.startswith(SAFETY_KEY_PREFIX)
            documents.append(
                Document(
                    text=_symptom_tree_text(appliance, symptom_key, tree),
                    doc_id=_stable_id("yaml", appliance, symptom_key),
                    metadata={
                        "appliance": appliance,
                        "symptom_key": symptom_key,
                        "source": f"app/knowledge/{appliance}.yaml#{symptom_key}",
                        "safety": is_safety,
                    },
                )
            )
    return documents


def library_docs_documents() -> list[Document]:
    """`docs/library/` passages (md/txt/pdf), each carrying only a `source` path."""
    if not LIBRARY_DOCS_DIR.exists():
        return []
    files = sorted(
        p
        for p in LIBRARY_DOCS_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in LIBRARY_DOC_SUFFIXES and p.name != "README.md"
    )
    if not files:
        return []

    from llama_index.core import SimpleDirectoryReader

    reader = SimpleDirectoryReader(input_files=[str(p) for p in files])
    raw_docs = reader.load_data()
    documents: list[Document] = []
    for i, doc in enumerate(raw_docs):
        file_path = Path(doc.metadata.get("file_path", str(files[min(i, len(files) - 1)])))
        try:
            source = str(file_path.relative_to(REPO_ROOT))
        except ValueError:
            source = str(file_path)
        doc.doc_id = _stable_id("docs_library", source, str(i))
        doc.metadata.update(
            {"appliance": None, "symptom_key": None, "source": source, "safety": False}
        )
        documents.append(doc)
    return documents


def build_documents() -> list[Document]:
    return yaml_documents() + library_docs_documents()


def ingest(path: str | None = None, model_name: str | None = None):
    """Rebuild the `appliance_library` collection from source. Returns `(client, index)`
    — caller owns the client and must call `client.close()` when done with it."""
    from llama_index.vector_stores.qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient

    resolved_path = path or qdrant_path()
    Path(resolved_path).mkdir(parents=True, exist_ok=True)

    client = QdrantClient(path=resolved_path)
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)

    vector_store = QdrantVectorStore(client=client, collection_name=COLLECTION_NAME)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    embed_model = FastEmbedLocalEmbedding(model_name=model_name or embed_model_name())
    documents = build_documents()

    index = VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
        embed_model=embed_model,
        transformations=[SentenceSplitter(chunk_size=1024)],
    )
    return client, index


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    resolved_path = qdrant_path()
    client, _index = ingest(resolved_path)
    try:
        count = client.count(COLLECTION_NAME).count
        logger.info(
            "ingested %d points into collection %r at %s",
            count,
            COLLECTION_NAME,
            resolved_path,
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
