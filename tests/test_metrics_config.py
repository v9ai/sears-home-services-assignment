"""Metric config tests (plan.md group 4) — checks name mappings and pinned
thresholds only; never constructs a real DeepEval metric (that requires
`OPENAI_API_KEY` and is exercised only under `make eval`, see evals/test_*.py)."""

from __future__ import annotations

import typing

import pytest

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


def test_openai_judge_model_honors_override(monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "gpt-4o-mini")
    assert thresholds.judge_model() == "gpt-4o-mini"


def test_deepseek_judge_model_raises_loudly_when_key_absent(monkeypatch):
    """A missing judge key must surface as a hard error at construction time, never a
    silent pass — the DeepSeek judge reads DEEPSEEK_API_KEY eagerly. (The `make eval`
    conftest turns this into a loud SKIP; here we pin that the underlying constructor
    refuses to proceed keyless rather than judging with no credential.)"""
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(KeyError):
        thresholds.judge_model()


def test_build_metrics_selects_named_builtins_and_rubrics(monkeypatch):
    """Keyless wiring check: under the OpenAI provider `judge_model()` is a plain model
    id (no key needed), so we can prove build_metrics maps names to the right metric
    classes without any live judge."""
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    built = metrics.build_metrics(["knowledge_retention"], ["safety_interrupt"])
    names = {type(m).__name__ for m in built}
    assert names == {"KnowledgeRetentionMetric", "ConversationalGEval"}


def test_build_metrics_empty_selection_is_empty(monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    assert metrics.build_metrics([], []) == []


def test_build_metrics_rejects_unknown_metric_name(monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    with pytest.raises(KeyError):
        metrics.build_metrics(["not_a_metric"], [])


def test_build_metrics_rejects_unknown_rubric_name(monkeypatch):
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    with pytest.raises(KeyError):
        metrics.build_metrics([], ["not_a_rubric"])


def test_every_builtin_and_rubric_factory_is_callable_and_pinned(monkeypatch):
    """No metric factory silently drops its threshold — each constructed metric carries
    the pinned value from thresholds.py (guards against a copy-paste threshold drift)."""
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "openai")
    expected = {
        "knowledge_retention": thresholds.KNOWLEDGE_RETENTION,
        "role_adherence": thresholds.ROLE_ADHERENCE,
        "conversation_completeness": thresholds.CONVERSATION_COMPLETENESS,
    }
    for name, factory in metrics.BUILTIN_METRICS.items():
        metric = factory("gpt-4o")
        assert metric.threshold == expected[name]
    for factory in metrics.RUBRIC_METRICS.values():
        metric = factory("gpt-4o")
        assert metric.threshold == thresholds.GEVAL_RUBRIC


# --- Judge-call transient-error retry (task #53) ------------------------------------
#
# The mandatory eval lane was reddening ~once per full run on transient DeepSeek judge
# failures (timeout / rate-limit / malformed-JSON). `thresholds._with_judge_retry` adds
# bounded retry around the judge model's generate/a_generate. The load-bearing property
# under test: it retries ERRORS but NEVER re-rolls a returned verdict — a genuine low
# score must pass through untouched, or the gate stops meaning anything.


class _FlakyJudge:
    """DeepEval-model-shaped fake: generate/a_generate raise a scripted list of
    exceptions, then return a fixed (verdict, cost). Records attempt count."""

    def __init__(self, errors, result=("verdict", 0.0)):
        self._errors = list(errors)
        self.result = result
        self.calls = 0

    def generate(self, *args, **kwargs):
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        return self.result

    async def a_generate(self, *args, **kwargs):
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        return self.result


@pytest.fixture
def _instant_backoff(monkeypatch):
    """Neutralize the real sleeps so retry tests run in microseconds."""
    monkeypatch.setattr(thresholds.time, "sleep", lambda *_: None)

    async def _no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(thresholds.asyncio, "sleep", _no_sleep)


def _deepeval_error(msg="Evaluation LLM outputted an invalid JSON"):
    from deepeval.errors import DeepEvalError

    return DeepEvalError(msg)


def test_judge_retry_recovers_from_a_transient_error_then_records_the_verdict(_instant_backoff):
    judge = _FlakyJudge([_deepeval_error()], result=("verdict", 0.0))
    thresholds._with_judge_retry(judge)
    assert judge.generate("prompt") == ("verdict", 0.0)
    assert judge.calls == 2  # failed once, succeeded on the retry


async def test_judge_retry_async_recovers_from_a_transient_error(_instant_backoff):
    judge = _FlakyJudge([_deepeval_error("timeout")], result=("v", 1.0))
    thresholds._with_judge_retry(judge)
    assert await judge.a_generate("prompt") == ("v", 1.0)
    assert judge.calls == 2


def test_judge_retry_gives_up_after_bounded_attempts_and_raises_the_real_error(_instant_backoff):
    final = _deepeval_error("still bad after retries")
    judge = _FlakyJudge([_deepeval_error("1"), _deepeval_error("2"), final])
    thresholds._with_judge_retry(judge)
    with pytest.raises(Exception) as excinfo:  # noqa: PT011 - DeepEvalError, asserted below
        judge.generate("prompt")
    assert excinfo.value is final  # the actual last error, not a swallowed/wrapped one
    # 1 initial attempt + len(_JUDGE_RETRY_BACKOFFS_S) retries.
    assert judge.calls == len(thresholds._JUDGE_RETRY_BACKOFFS_S) + 1


def test_judge_retry_never_rerolls_a_returned_low_score(_instant_backoff):
    """THE correctness constraint: a successfully returned verdict — even a low score —
    is passed through on the first call with ZERO retries. Re-rolling a real verdict
    would corrupt the gate."""
    judge = _FlakyJudge([], result=("low-score verdict", 0.0))
    thresholds._with_judge_retry(judge)
    assert judge.generate("prompt") == ("low-score verdict", 0.0)
    assert judge.calls == 1


async def test_judge_retry_never_rerolls_a_returned_low_score_async(_instant_backoff):
    judge = _FlakyJudge([], result=("low-score verdict", 0.0))
    thresholds._with_judge_retry(judge)
    assert await judge.a_generate("prompt") == ("low-score verdict", 0.0)
    assert judge.calls == 1


def test_judge_retry_does_not_retry_a_nontransient_error(_instant_backoff):
    """A deterministic failure (programming error, unexpected type) must surface on the
    first attempt, not burn retries or get masked as transient."""
    judge = _FlakyJudge([KeyError("deterministic bug")])
    thresholds._with_judge_retry(judge)
    with pytest.raises(KeyError):
        judge.generate("prompt")
    assert judge.calls == 1


def test_transient_judge_error_set_includes_timeouts_ratelimits_and_malformed_json():
    import openai
    from deepeval.errors import DeepEvalError

    transient = thresholds._transient_judge_errors()
    for cls in (
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.RateLimitError,
        openai.InternalServerError,
        DeepEvalError,
    ):
        assert cls in transient
