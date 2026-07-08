"""Embedded-Qdrant retrieval store for the appliance-library RAG feature
(`2026-07-08-appliance-library-qdrant/requirements.md` Decisions 1-2).

Flag-gated: `app/tools/library_tools.py` decides whether the tool that calls
`retrieve()` is even registered, based on `LIBRARY_RAG_ENABLED`. This module itself
must stay side-effect-free at import time — no Qdrant client, no FastEmbed model
download — so importing it (e.g. transitively, from a test) never touches the
filesystem or network when the flag is off. Everything real happens lazily inside
`get_store()` / `QdrantLibraryStore._get_index()`, on first `retrieve()` call.

Deps are exactly `llama-index-vector-stores-qdrant` + `fastembed` (requirements.md
Contract shapes) — no separate `llama-index-embeddings-fastembed` adapter package;
`FastEmbedLocalEmbedding` below is a ~20-line `BaseEmbedding` wrapper over
`fastembed.TextEmbedding` instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from llama_index.core.embeddings import BaseEmbedding
from pydantic import PrivateAttr

COLLECTION_NAME = "appliance_library"
DEFAULT_QDRANT_PATH = "data/qdrant"
DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"


def qdrant_path() -> str:
    return os.environ.get("QDRANT_PATH", DEFAULT_QDRANT_PATH)


def embed_model_name() -> str:
    return os.environ.get("EMBED_MODEL", DEFAULT_EMBED_MODEL)


class FastEmbedLocalEmbedding(BaseEmbedding):
    """Local, offline, zero-API-cost embedding (requirements.md Decision 2).

    BGE models are asymmetric — `query_embed` applies the retrieval-instruction
    prefix fastembed knows for this model family, `passage_embed` does not — so
    queries and indexed passages intentionally go through different fastembed calls.
    """

    _model: Any = PrivateAttr()

    def __init__(self, model_name: str | None = None, **kwargs: Any) -> None:
        super().__init__(model_name=model_name or embed_model_name(), **kwargs)
        from fastembed import TextEmbedding

        object.__setattr__(self, "_model", TextEmbedding(model_name=self.model_name))

    @classmethod
    def class_name(cls) -> str:
        return "FastEmbedLocalEmbedding"

    def _get_query_embedding(self, query: str) -> list[float]:
        return next(iter(self._model.query_embed([query]))).tolist()

    def _get_text_embedding(self, text: str) -> list[float]:
        return next(iter(self._model.passage_embed([text]))).tolist()

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.passage_embed(texts)]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)


@dataclass(frozen=True)
class LibraryHit:
    """One scored retrieval result, attributed back to its source document.

    Mirrors the document metadata contract (requirements.md Contract shapes):
    ``{appliance, symptom_key, source, safety, brand, model_number}``. YAML-derived
    hits carry ``appliance``/``symptom_key``; ``docs/library/`` passages carry only
    ``source`` plus, optionally, ``brand``/``model_number`` when the source document's
    frontmatter set them — free-text like ``CaseFile.brand``/``model``
    (`app/contracts.py`), not a validated enum.
    """

    text: str
    score: float
    appliance: str | None
    symptom_key: str | None
    source: str
    safety: bool
    brand: str | None = None
    model_number: str | None = None


class LibraryStore(Protocol):
    """The interface `app/tools/library_tools.py` codes against — real or fake."""

    def retrieve(self, query: str, k: int = 3) -> list[LibraryHit]: ...


class QdrantLibraryStore:
    """Real store: embedded Qdrant (`QdrantClient(path=...)`) + FastEmbed.

    Connection + embedding-model construction are deferred to the first `retrieve()`
    call (`_get_index`), never `__init__` — importing/instantiating this class alone
    has no I/O side effects.
    """

    def __init__(self, path: str | None = None, model_name: str | None = None) -> None:
        self._path = path or qdrant_path()
        self._model_name = model_name or embed_model_name()
        self._index: Any = None

    def _get_index(self) -> Any:
        if self._index is not None:
            return self._index
        from llama_index.core import VectorStoreIndex
        from llama_index.vector_stores.qdrant import QdrantVectorStore
        from qdrant_client import QdrantClient

        client = QdrantClient(path=self._path)
        # index_doc_id=False: embedded/local Qdrant has no payload indexes (requirements.md
        # Decision 1 caveat) and we never filter/delete by doc_id, so the default just
        # produces a harmless "Payload indexes have no effect" warning on every open.
        vector_store = QdrantVectorStore(
            client=client, collection_name=COLLECTION_NAME, index_doc_id=False
        )
        embed_model = FastEmbedLocalEmbedding(model_name=self._model_name)
        self._index = VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)
        return self._index

    def retrieve(self, query: str, k: int = 3) -> list[LibraryHit]:
        index = self._get_index()
        retriever = index.as_retriever(similarity_top_k=k)
        nodes = retriever.retrieve(query)
        hits: list[LibraryHit] = []
        for scored_node in nodes:
            meta = scored_node.node.metadata or {}
            hits.append(
                LibraryHit(
                    text=scored_node.node.get_content(),
                    score=float(scored_node.score or 0.0),
                    appliance=meta.get("appliance"),
                    symptom_key=meta.get("symptom_key"),
                    source=meta.get("source", "unknown"),
                    safety=bool(meta.get("safety", False)),
                    brand=meta.get("brand"),
                    model_number=meta.get("model_number"),
                )
            )
        return hits


_store: LibraryStore | None = None


def get_store() -> LibraryStore:
    """Return the process-wide store, constructing the real one on first use.

    Test seam: call `set_store(fake)` to inject a fake/stub (COORDINATION.md §4
    stub-seam convention) so unit tests never need a real embedding-model download.
    """
    global _store
    if _store is None:
        _store = QdrantLibraryStore()
    return _store


def set_store(store: LibraryStore | None) -> None:
    """Inject a fake store for tests, or pass None to reset to the lazy real one."""
    global _store
    _store = store


def retrieve(query: str, k: int = 3) -> list[LibraryHit]:
    """Top-`k` scored library hits for `query`. Real store lazily connects on first call."""
    return get_store().retrieve(query, k=k)
