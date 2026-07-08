"""Pinned metric thresholds (requirements.md → Contract shapes). A miss fails the gate.

Knowledge Retention >= 0.8 · Role Adherence >= 0.7 · Conversation Completeness >= 0.7
G-Eval rubrics (safety-interrupt, booking-confirmation, photo-findings) >= 0.8
"""

from __future__ import annotations

KNOWLEDGE_RETENTION = 0.8
ROLE_ADHERENCE = 0.7
CONVERSATION_COMPLETENESS = 0.7
GEVAL_RUBRIC = 0.8

JUDGE_MODEL = "gpt-4o"
