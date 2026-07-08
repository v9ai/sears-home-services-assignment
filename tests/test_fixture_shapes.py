"""Every authored fixture's `case_file` must conform to `app.contracts.CaseFile` —
the shared contract all fixture transcripts must respect, regardless of whether the
owning feature (scheduling/visual) has merged yet."""

from __future__ import annotations

from app.contracts import CaseFile
from evals.fixture_loader import load_fixture
from evals.scenarios.schema import load_scenarios


def test_every_scenario_has_a_recorded_fixture():
    for scenario in load_scenarios():
        # Raises FixtureNotFoundError if missing.
        load_fixture(scenario.id)


def test_every_fixture_case_file_matches_the_contract():
    for scenario in load_scenarios():
        fixture = load_fixture(scenario.id)
        CaseFile.model_validate(fixture["case_file"])


def test_every_fixture_has_turns_and_flags():
    for scenario in load_scenarios():
        fixture = load_fixture(scenario.id)
        assert fixture["turns"], f"{scenario.id} fixture has no turns"
        assert isinstance(fixture["turns"][0]["role"], str)
        assert set(fixture["flags"]) >= {"safety_interrupt", "booking_row", "reasked_fields"}
