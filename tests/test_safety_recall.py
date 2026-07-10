"""Recall suite for the safety-interrupt detector (bugfix-loop B1).

The original suite proves the regexes match the phrasings they were written
for. This suite probes the natural phrasings a live caller actually uses —
participles ("it's smoking"), prepositional constructions ("smell of gas",
"water in the outlet"), and standard hazard synonyms (propane, fumes, arcing).
Every positive case here was a confirmed false negative before the fix.

It also pins the intended safe-side behavior for negated mentions: "no gas
smell" still trips the interrupt. Over-triggering is the documented, deliberate
direction for a deterministic pre-LLM gate.
"""

from __future__ import annotations

import pytest

from app.agent.safety import detect_safety_trigger

# --- smoke: participle / adjective forms -----------------------------------

@pytest.mark.parametrize(
    "utterance",
    [
        "the dryer is smoking",
        "my oven started smoking when I turned it on",
        "there's something smoking behind the washer",
        "it got all smoky in the kitchen when the dishwasher ran",
    ],
)
def test_smoke_detects_participle_and_adjective_forms(utterance: str) -> None:
    assert detect_safety_trigger(utterance) == "smoke"


def test_smoked_past_tense_noise_still_does_not_trigger() -> None:
    # Existing false-positive guard must survive the recall fix.
    assert detect_safety_trigger("we smoked some ribs and now the fridge smells") is None


# --- water near electrics: prepositions, wetness, dripping ------------------

@pytest.mark.parametrize(
    "utterance",
    [
        "there's water in the outlet",
        "water got on the wiring behind the washer",
        "water is leaking into the electrical panel",
        "some water splashed onto the plug",
        "the outlet is wet",
        "there's a wet outlet next to the dishwasher",
        "something is dripping onto the plug",
        "the hose is leaking into the outlet",
    ],
)
def test_water_on_in_or_wetting_electrics_triggers(utterance: str) -> None:
    assert detect_safety_trigger(utterance) == "water_near_electrics"


def test_water_far_from_electrics_still_does_not_trigger() -> None:
    assert detect_safety_trigger("there is water pooling on the kitchen floor") is None


def test_wet_clothes_do_not_trigger() -> None:
    assert detect_safety_trigger("the clothes come out wet after the dry cycle") is None


# --- gas: "smell of", propane, fumes ----------------------------------------

@pytest.mark.parametrize(
    "utterance",
    [
        "I noticed a smell of gas near the oven",
        "there's a faint smell of gas",
        "I smell propane in the kitchen",
        "there's a propane smell by the range",
        "we've got a propane leak I think",
        "I'm smelling fumes from the oven",
        "there's a strong smell of fumes",
    ],
)
def test_gas_covers_of_construction_propane_and_fumes(utterance: str) -> None:
    assert detect_safety_trigger(utterance) == "gas_smell"


def test_propane_appliance_ownership_alone_does_not_trigger() -> None:
    assert detect_safety_trigger("I have a propane range that won't ignite") is None


# --- burning: "smell of burning" --------------------------------------------

@pytest.mark.parametrize(
    "utterance",
    [
        "there's a smell of burning coming from the dryer",
        "I noticed a smell of burnt plastic",
    ],
)
def test_burning_covers_of_construction(utterance: str) -> None:
    assert detect_safety_trigger(utterance) == "burning_smell"


# --- sparking: arcing synonym ------------------------------------------------

@pytest.mark.parametrize(
    "utterance",
    [
        "the outlet is arcing",
        "I saw an arc at the plug when I unplugged it",
        "it arced when the compressor kicked on",
    ],
)
def test_sparking_covers_arcing(utterance: str) -> None:
    assert detect_safety_trigger(utterance) == "sparking"


def test_arc_unrelated_words_do_not_trigger() -> None:
    assert detect_safety_trigger("the door swings in an arch and the search is over") is None


# --- negation: safe-side over-trigger is deliberate and pinned ---------------

@pytest.mark.parametrize(
    "utterance",
    [
        "no, there's no gas smell, just a rattling noise",
        "I don't see any smoke, it just won't spin",
    ],
)
def test_negated_hazard_mentions_still_trigger_by_design(utterance: str) -> None:
    """Any mention halts troubleshooting — including denials.

    The interrupt is a deterministic pre-LLM gate; erring toward a safety
    read-back on a denial is the accepted cost. This test pins the direction
    so a future 'fix' that adds negation parsing is a conscious decision.
    """
    assert detect_safety_trigger(utterance) is not None
