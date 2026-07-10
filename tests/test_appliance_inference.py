"""Appliance inference from the issue summary (bugfix-loop T9, hermetic half).

`_infer_appliance_type` decides how a booking is filed. Before the fix it
scanned the alias dict in insertion order with substring matching, so any
summary containing "dishwasher" hit the "washer" keyword first and the
appointment was filed under the wrong appliance — a live Tier-2 data bug.
This suite pins the full alias table and the longest-match-wins rule.
"""

from __future__ import annotations

import pytest

from app.tools.scheduling_tools import _infer_appliance_type


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        # The collision that motivated the fix.
        ("my dishwasher will not drain", "dishwasher"),
        ("the dish washer leaks on the floor", "dishwasher"),
        # Washer proper still resolves.
        ("washer bangs during spin", "washer"),
        ("my washing machine leaks", "washer"),
        ("dryer squeals and no heat", "dryer"),
        # Refrigerator family.
        ("refrigerator not cooling", "refrigerator"),
        ("the fridge is warm", "refrigerator"),
        ("freezer full of frost", "refrigerator"),
        # Oven family.
        ("oven won't preheat", "oven"),
        ("stove burner won't light", "oven"),
        ("the range clicks forever", "oven"),
        # HVAC aliases, including the fragile padded/punctuated ones.
        ("hvac unit rattles", "hvac"),
        ("air conditioner is dead", "hvac"),
        ("no air conditioning upstairs", "hvac"),
        ("my a/c blows warm air", "hvac"),
        ("the ac is not cooling", "hvac"),
        ("furnace short-cycles", "hvac"),
        ("heater never turns on", "hvac"),
        ("thermostat screen is blank", "hvac"),
    ],
)
def test_alias_table_files_the_right_appliance(summary: str, expected: str) -> None:
    assert _infer_appliance_type(summary) == expected


def test_unknown_summary_returns_none() -> None:
    assert _infer_appliance_type("the garage door opener hums") is None


def test_case_insensitive() -> None:
    assert _infer_appliance_type("My DISHWASHER is Broken") == "dishwasher"
    assert _infer_appliance_type("The AC died") == "hvac"
