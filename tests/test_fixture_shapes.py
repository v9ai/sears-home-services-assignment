"""Every authored fixture's `case_file` must conform to `app.contracts.CaseFile` —
the shared contract all fixture transcripts must respect, regardless of whether the
owning feature (scheduling/visual) has merged yet."""

from __future__ import annotations

import json

import pytest

from app.contracts import CaseFile
from evals.fixture_loader import FixtureNotFoundError, load_fixture
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


def test_every_fixture_turn_has_role_and_text():
    # A fixture whose turns are structurally wrong would silently break the adapter and
    # the structural runner; pin the per-turn shape here at the source.
    for scenario in load_scenarios():
        fixture = load_fixture(scenario.id)
        for i, turn in enumerate(fixture["turns"]):
            assert turn.get("role") in {"user", "agent", "assistant"}, (
                f"{scenario.id} turn {i} has bad role {turn.get('role')!r}"
            )
            assert isinstance(turn.get("text"), str), f"{scenario.id} turn {i} missing text"


def test_missing_fixture_raises_fixture_not_found(tmp_path):
    with pytest.raises(FixtureNotFoundError, match="no recorded fixture"):
        load_fixture("does_not_exist", root=tmp_path)


def test_load_fixture_reads_a_written_transcript(tmp_path):
    payload = {
        "turns": [{"role": "user", "text": "hi"}],
        "case_file": {},
        "flags": {"safety_interrupt": False, "booking_row": False, "reasked_fields": []},
    }
    (tmp_path / "scn.json").write_text(json.dumps(payload))
    loaded = load_fixture("scn", root=tmp_path)
    assert loaded == payload


def test_malformed_fixture_json_raises_loudly(tmp_path):
    # A truncated/corrupt fixture must fail loudly at load, never be treated as empty.
    (tmp_path / "corrupt.json").write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        load_fixture("corrupt", root=tmp_path)
