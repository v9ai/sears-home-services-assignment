"""Metric config tests (plan.md group 4) — checks name mappings and pinned
thresholds only; never constructs a real DeepEval metric (that requires
`OPENAI_API_KEY` and is exercised only under `make eval`, see evals/test_*.py)."""

from __future__ import annotations

import typing

from evals import metrics, thresholds
from evals.scenarios.schema import MetricName, RubricName


def test_builtin_metric_names_match_scenario_schema_literals():
    assert set(metrics.BUILTIN_METRICS) == set(typing.get_args(MetricName))


def test_rubric_names_match_scenario_schema_literals():
    assert set(metrics.RUBRIC_METRICS) == set(typing.get_args(RubricName))


def test_pinned_thresholds_match_requirements():
    assert thresholds.KNOWLEDGE_RETENTION == 0.8
    assert thresholds.ROLE_ADHERENCE == 0.7
    assert thresholds.CONVERSATION_COMPLETENESS == 0.7
    assert thresholds.GEVAL_RUBRIC == 0.8
    assert thresholds.JUDGE_MODEL == "gpt-4o"
