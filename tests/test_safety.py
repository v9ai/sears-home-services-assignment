"""Safety-interrupt detector unit tests (mission non-negotiable 1)."""

from __future__ import annotations

import pytest

from app.agent.safety import SAFETY_RESPONSE, detect_safety_trigger


@pytest.mark.parametrize(
    "text",
    [
        "I smell gas near the oven",
        "it smells like gas in the kitchen",
        "there's a rotten egg smell by the furnace",
    ],
)
def test_gas_smell_triggers(text: str) -> None:
    assert detect_safety_trigger(text) == "gas_smell"


def test_sparking_triggers() -> None:
    assert detect_safety_trigger("I see sparks coming from the dryer outlet") == "sparking"


def test_burning_smell_triggers() -> None:
    assert detect_safety_trigger("I smell something burning from the dryer") == "burning_smell"


def test_smoke_triggers() -> None:
    assert detect_safety_trigger("there's smoke coming out of the oven") == "smoke"


def test_water_near_electrics_triggers() -> None:
    assert detect_safety_trigger("there's water pooling near the outlet") == "water_near_electrics"
    assert detect_safety_trigger("water is touching the electrical panel") == "water_near_electrics"


@pytest.mark.parametrize(
    "text",
    [
        "my washer is making a grinding noise and shows error E3",
        "it's leaking a bit under the door",
        "the dryer takes forever to dry a full load",
        "the ice maker stopped working last week",
    ],
)
def test_benign_symptoms_do_not_trigger(text: str) -> None:
    assert detect_safety_trigger(text) is None


def test_safety_response_offers_shutoff_and_scheduling() -> None:
    lowered = SAFETY_RESPONSE.lower()
    assert "turn off" in lowered
    assert "schedul" in lowered
