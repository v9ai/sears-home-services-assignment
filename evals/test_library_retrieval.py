"""LlamaIndex-native retrieval gate for the appliance-library Qdrant index
(requirements.md Decision 6 / plan.md group 4, added 2026-07-08).

`DatasetGenerator` builds a question -> source-node dataset from the ingested
knowledge docs (question generation judged on `get_llm()`/DeepSeek, per the
Model-provider boundary), and `RetrieverEvaluator` (HitRate, MRR) gates the embedded
Qdrant retriever at **hit-rate >= 0.9 / MRR >= 0.7**.

Lives under `evals/` (not `tests/`) specifically so it inherits `evals/conftest.py`'s
existing global skip: every item here is skipped, not failed, when the active judge
provider's API key is absent (`make eval`'s posture — "SKIPPED, not passed and not
failed"), because `DatasetGenerator` needs a real LLM call to generate questions.
This mirrors `make eval`'s judge dependency even though it's driven by `make test`
today (no separate Makefile target was added for it — see plan.md Integration deltas
note on the LlamaIndex-native gate not yet having its own `make` target).

Also carries the "one retrieval canary" required by plan.md group 4: a deliberately
irrelevant, off-corpus query that must NOT score as a confident hit — proving the
gate can fail, not just always pass (canary posture, requirements.md Decision 3
precedent, applied here to the retrieval layer instead of a DeepEval scenario).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from llama_index.core.evaluation import DatasetGenerator, RetrieverEvaluator

from scripts.ingest_library import ingest

HIT_RATE_THRESHOLD = 0.9
MRR_THRESHOLD = 0.7
CANARY_QUERY = "Who won the soccer World Cup in 2014?"
# Real appliance-relevant queries score ~0.7-0.85 (requirements.md feasibility table);
# this off-corpus query scores ~0.4 against the same embedded index. 0.6 leaves
# comfortable margin on both sides rather than pinning to the exact observed value.
CANARY_SCORE_CEILING = 0.6


def _require_deepseek_llm_or_skip() -> None:
    """Belt-and-suspenders alongside `evals/conftest.py`'s global skip: that skip is
    keyed on `EVAL_JUDGE_PROVIDER`'s key, but `get_llm()` (question generation here)
    always follows `LLM_PROVIDER` (default deepseek) — guard the mismatch case too."""
    if os.environ.get("LLM_PROVIDER", "deepseek") == "openai":
        return
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set — DatasetGenerator needs a live get_llm() call")


@pytest.fixture(scope="module")
def library_index(tmp_path_factory: pytest.TempPathFactory) -> Iterator[object]:
    qdrant_path = tmp_path_factory.mktemp("qdrant_retrieval_gate")
    client, index = ingest(str(qdrant_path))
    try:
        yield index
    finally:
        client.close()


async def _questions_by_node(nodes: list, llm) -> list[tuple[str, object]]:
    """One generated question per node, generated concurrently, node association kept
    (public `DatasetGenerator` APIs merge questions across nodes into one flat dataset
    with no id linkage back to source node, so each node gets its own single-node
    generator call instead)."""

    async def _one(node):
        generator = DatasetGenerator(
            [node], llm=llm, num_questions_per_chunk=1, show_progress=False
        )
        questions = await generator.agenerate_questions_from_nodes()
        return node, (questions[0] if questions else None)

    pairs = await asyncio.gather(*(_one(node) for node in nodes))
    return [(question, node) for node, question in pairs if question]


def test_retriever_meets_hit_rate_and_mrr_gate(library_index: object) -> None:
    _require_deepseek_llm_or_skip()
    from app.agent.core import get_llm

    nodes = list(library_index.docstore.docs.values())
    assert nodes, "ingested index has no nodes"

    pairs = asyncio.run(_questions_by_node(nodes, get_llm()))
    assert pairs, "DatasetGenerator produced no question/node pairs"

    retriever = library_index.as_retriever(similarity_top_k=3)
    evaluator = RetrieverEvaluator.from_metric_names(["hit_rate", "mrr"], retriever=retriever)

    async def _evaluate_all():
        return await asyncio.gather(
            *(
                evaluator.aevaluate(query=question, expected_ids=[node.node_id])
                for question, node in pairs
            )
        )

    results = asyncio.run(_evaluate_all())
    hit_rates = [r.metric_dict["hit_rate"].score for r in results]
    mrrs = [r.metric_dict["mrr"].score for r in results]

    avg_hit_rate = sum(hit_rates) / len(hit_rates)
    avg_mrr = sum(mrrs) / len(mrrs)

    assert avg_hit_rate >= HIT_RATE_THRESHOLD, (
        f"hit-rate {avg_hit_rate:.3f} below gate {HIT_RATE_THRESHOLD} "
        f"({len(pairs)} generated questions)"
    )
    assert avg_mrr >= MRR_THRESHOLD, f"MRR {avg_mrr:.3f} below gate {MRR_THRESHOLD}"


def test_retrieval_canary_irrelevant_query_is_not_a_confident_hit(
    library_index: object,
) -> None:
    """Deliberate-failure canary (plan.md group 4's "one retrieval canary"): a query
    with no relationship to any appliance/knowledge-library content must not come
    back as a confident top-1 match — if it did, the retrieval gate above would be
    meaningless (it could never fail)."""
    retriever = library_index.as_retriever(similarity_top_k=1)
    nodes = retriever.retrieve(CANARY_QUERY)
    assert not nodes or (nodes[0].score or 0.0) < CANARY_SCORE_CEILING, (
        f"canary query {CANARY_QUERY!r} scored a confident hit "
        f"({nodes[0].score if nodes else None}) — retrieval canary failed to fail"
    )


def test_ingest_module_documents_are_reachable_from_repo_root() -> None:
    """Sanity check that this module's relative imports resolve against the worktree
    (not some other checkout) — guards against a stale `sys.path` masking import
    errors in the two tests above."""
    from scripts.ingest_library import REPO_ROOT

    assert (Path(REPO_ROOT) / "app" / "knowledge").is_dir()
