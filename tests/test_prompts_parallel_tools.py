"""Prompt static assert for P2-1 (latency-engineering): independent tool calls for one
caller turn must be issued together in a single LLM response — each extra round trip
is caller-facing dead air (measured: 2-tool turns dominated the failing e2e
submit_to_first_token in data/latency/20260709T211909Z.json)."""

from __future__ import annotations

from app.agent.prompts import NON_NEGOTIABLES, build_system_prompt
from app.contracts import CaseFile


def test_non_negotiables_direct_parallel_tool_calls():
    assert "single response" in NON_NEGOTIABLES
    assert "round trip" in NON_NEGOTIABLES


def test_parallel_tool_guidance_reaches_the_system_prompt():
    prompt = build_system_prompt(CaseFile())
    assert "ALL the independent tool calls" in prompt
