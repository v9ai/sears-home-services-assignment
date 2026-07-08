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


def test_judge_provider_boundary(monkeypatch):
    """tech-stack.md Model-provider boundary: DeepSeek judges by default; OpenAI is
    opt-in via EVAL_JUDGE_PROVIDER (and is reserved for vision/STT/TTS otherwise)."""
    monkeypatch.delenv("EVAL_JUDGE_PROVIDER", raising=False)
    assert thresholds.judge_provider() == "deepseek"
    assert thresholds.judge_key_env() == "DEEPSEEK_API_KEY"
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    assert thresholds.judge_key_env() == "OPENAI_API_KEY"
    assert thresholds.judge_model() == thresholds.JUDGE_MODEL_OPENAI
