"""Pinned metric thresholds + judge model (requirements.md → Contract shapes).

Knowledge Retention >= 0.8 · Role Adherence >= 0.7 · Conversation Completeness >= 0.7
G-Eval rubrics (safety-interrupt, booking-confirmation, photo-findings) >= 0.8

Judge: **DeepSeek `deepseek-chat`** by default (user directive 2026-07-08 — DeepSeek
for all LLM calls; OpenAI only for vision/STT/TTS). `EVAL_JUDGE_PROVIDER=openai`
switches back to `gpt-4o` when a funded OpenAI key is available. Same-provider
judging (agent and judge both DeepSeek) is a recorded bias risk; the mitigation is
the mandatory canary suite — the judge provably fails bad transcripts.
"""

from __future__ import annotations

import asyncio
import functools
import os
import time

KNOWLEDGE_RETENTION = 0.8
ROLE_ADHERENCE = 0.7
CONVERSATION_COMPLETENESS = 0.7
GEVAL_RUBRIC = 0.8

# Kept for introspection/tests; the live default provider is deepseek.
JUDGE_MODEL_OPENAI = "gpt-4o"
JUDGE_MODEL_DEEPSEEK = "deepseek-chat"


def judge_provider() -> str:
    return os.environ.get("EVAL_JUDGE_PROVIDER", "deepseek")


def judge_key_env() -> str:
    """Name of the env var the active judge provider needs."""
    return "OPENAI_API_KEY" if judge_provider() == "openai" else "DEEPSEEK_API_KEY"


# Backoff (seconds) applied *between* judge-call attempts; length == retries after the
# first try (mirrors the vision-retry shape in app/uploads/routes.py). Worst-case added
# latency is the sum (0.5 + 1.0 = 1.5s) per judged metric — negligible against a judge
# call, and it only pays out when a call actually fails.
_JUDGE_RETRY_BACKOFFS_S = (0.5, 1.0)


def _transient_judge_errors() -> tuple[type[BaseException], ...]:
    """Judge-call failures worth retrying, resolved lazily so importing this module
    needs neither `openai` nor `deepeval` (the key-skip gate in evals/conftest.py must
    import thresholds without a judge backend present).

    A network blip, timeout, rate limit, or a transient 5xx clears on a retry; so does a
    malformed-JSON judge response (`DeepEvalError` — "Evaluation LLM outputted an invalid
    JSON"), which for a DeepSeek judge is an intermittent formatting failure, not a real
    verdict. Everything else (schema mismatches, programming errors) is deterministic and
    is re-raised on the first occurrence.
    """
    import openai
    from deepeval.errors import DeepEvalError

    return (
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.RateLimitError,
        openai.InternalServerError,
        DeepEvalError,
    )


def _with_judge_retry(model):
    """Wrap a DeepEval judge model INSTANCE so its `generate`/`a_generate` retry a
    bounded number of times on transient call failures.

    CRITICAL correctness property: these failures are raised *inside* the judge call,
    *before* any score exists — a successful call RETURNS a `(verdict, cost)` pair and
    the metric computes the score downstream. So a retry only ever re-attempts a call
    that produced no usable response; a genuine low score is a returned value and is
    NEVER re-rolled (re-rolling a real verdict would corrupt the gate's meaning). Only
    the DeepSeek judge is an instance we can wrap — the OpenAI branch hands DeepEval a
    model-id string it constructs internally, so it keeps DeepEval's own retry.
    """
    transient = _transient_judge_errors()
    orig_generate = model.generate
    orig_a_generate = model.a_generate
    last_backoff = len(_JUDGE_RETRY_BACKOFFS_S)

    @functools.wraps(orig_generate)
    def generate(*args, **kwargs):
        for attempt in range(last_backoff + 1):
            try:
                return orig_generate(*args, **kwargs)
            except transient:
                if attempt == last_backoff:
                    raise
                time.sleep(_JUDGE_RETRY_BACKOFFS_S[attempt])

    @functools.wraps(orig_a_generate)
    async def a_generate(*args, **kwargs):
        for attempt in range(last_backoff + 1):
            try:
                return await orig_a_generate(*args, **kwargs)
            except transient:
                if attempt == last_backoff:
                    raise
                await asyncio.sleep(_JUDGE_RETRY_BACKOFFS_S[attempt])

    model.generate = generate
    model.a_generate = a_generate
    return model


def judge_model():
    """Judge for DeepEval metrics — a model instance (deepseek) or id string (openai).

    Constructed lazily (never at import): DeepSeekModel resolves its API key eagerly.
    The deepseek instance is wrapped with bounded transient-error retry so a flaky judge
    call doesn't red the mandatory eval lane (`_with_judge_retry` — errors retry, scores
    never do).
    """
    if judge_provider() == "openai":
        return os.environ.get("EVAL_JUDGE_MODEL", JUDGE_MODEL_OPENAI)
    from deepeval.models import DeepSeekModel

    return _with_judge_retry(
        DeepSeekModel(
            model=os.environ.get("EVAL_JUDGE_MODEL", JUDGE_MODEL_DEEPSEEK),
            api_key=os.environ["DEEPSEEK_API_KEY"],
            temperature=0,
        )
    )
