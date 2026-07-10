"""Zip validation on the scheduling search (appt-req-loop f1).

`find_technicians` must answer a malformed zip with a structured `invalid_zip`
status — asking the agent to re-confirm — instead of silently matching no
technicians and sending the conversation down the wrong "no coverage" path. The
invalid-zip path returns before any DB session opens, so these tests are hermetic.
"""

from __future__ import annotations

import json

import pytest

from app.tools.scheduling_tools import _normalize_zip, find_technicians


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("60614", "60614"),
        (" 60614 ", "60614"),
        ("60614-1234", "60614"),
        ("60614 1234", "60614"),
        ("6061", None),
        ("606140", None),
        ("abcde", None),
        ("6061a", None),
        ("", None),
        ("  ", None),
    ],
)
def test_normalize_zip(raw, expected):
    assert _normalize_zip(raw) == expected


async def test_find_technicians_rejects_invalid_zip_before_searching():
    result = json.loads(await find_technicians("not-a-zip", "washer"))
    assert result["status"] == "invalid_zip"
    assert "re-confirm" in result["message"].lower()


async def test_find_technicians_invalid_zip_never_persists_to_case_file():
    """A mis-heard zip must not pollute the case file the never-re-ask contract
    treats as confirmed truth."""
    from app.agent.state import current_case_file
    from app.contracts import CaseFile

    case_file = CaseFile()
    token = current_case_file.set(case_file)
    try:
        await find_technicians("9810", "washer")
    finally:
        current_case_file.reset(token)
    assert case_file.customer.zip is None
