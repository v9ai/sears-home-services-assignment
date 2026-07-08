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

import os

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


def judge_model():
    """Judge for DeepEval metrics — a model instance (deepseek) or id string (openai).

    Constructed lazily (never at import): DeepSeekModel resolves its API key eagerly.
    """
    if judge_provider() == "openai":
        return os.environ.get("EVAL_JUDGE_MODEL", JUDGE_MODEL_OPENAI)
    from deepeval.models import DeepSeekModel

    return DeepSeekModel(
        model=os.environ.get("EVAL_JUDGE_MODEL", JUDGE_MODEL_DEEPSEEK),
        api_key=os.environ["DEEPSEEK_API_KEY"],
        temperature=0,
    )
