"""`make transcript` gate: the full matrix run plus hermetic unit tests of the
runner's decision logic (skip-vs-pass semantics, canary anti-vacuity, error paths).

A green transcript gate must MEAN something: a gated scenario must SKIP (never count
as a pass), a missing fixture must ERROR (never a silent skip), and a canary that
fails to fail must be flagged as a harness bug.
"""

from __future__ import annotations

from typing import Any

import pytest

from evals.fixture_loader import FixtureNotFoundError
from evals.scenarios.schema import Scenario
from scripts import transcript_runner
from scripts.transcript_runner import _run_canaries, _run_matrix, run


def _scenario(scenario_id: str, *, canary: bool = False, **overrides: Any) -> Scenario:
    data: dict[str, Any] = {
        "id": scenario_id,
        "feature": "core",
        "turns": [{"caller": "hi"}],
        "assert": {"facts": {"appliance_type": "washer"}},
        "canary": canary,
        **overrides,
    }
    return Scenario.model_validate(data)


_PASSING_FIXTURE = {
    "case_file": {"appliance_type": "washer"},
    "flags": {"safety_interrupt": False, "booking_row": False, "reasked_fields": []},
}
_FAILING_FIXTURE = {
    "case_file": {"appliance_type": "dryer"},  # mismatches the asserted "washer"
    "flags": {"safety_interrupt": False, "booking_row": False, "reasked_fields": []},
}


# --- The real end-to-end gate -------------------------------------------------------


def test_transcript_runner_matrix_passes_and_canaries_fail_as_expected(capsys):
    exit_code = run()
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out
    assert "transcript gate: PASS" in captured.out


def test_transcript_runner_activates_previously_gated_scenarios(capsys):
    # Post-integration (COORDINATION.md §5): scheduling + visual are merged, so their
    # `requires:`-gated scenarios run instead of skipping.
    run()
    captured = capsys.readouterr()
    assert "requires unmet" not in captured.out
    assert "PASS  scheduling_happy_booking" in captured.out
    assert "PASS  visual_email_spellback" in captured.out


# --- Matrix decision logic (hermetic) -----------------------------------------------


def test_matrix_passing_scenario_is_not_a_failure(monkeypatch, capsys):
    monkeypatch.setattr(transcript_runner, "load_fixture", lambda _id: _PASSING_FIXTURE)
    failed = _run_matrix([_scenario("s_pass")], live=False)
    assert failed is False
    assert "PASS  s_pass" in capsys.readouterr().out


def test_matrix_failing_scenario_is_reported_as_failure(monkeypatch, capsys):
    monkeypatch.setattr(transcript_runner, "load_fixture", lambda _id: _FAILING_FIXTURE)
    failed = _run_matrix([_scenario("s_fail")], live=False)
    assert failed is True
    out = capsys.readouterr().out
    assert "FAIL  s_fail" in out
    assert "appliance_type" in out  # the specific defect is surfaced


def test_gated_scenario_skips_and_is_never_counted_as_pass(monkeypatch, capsys):
    # requires unmet -> SKIP. A skip must not turn into a silent PASS, and (since a
    # feature simply hasn't merged) must not fail the gate either.
    monkeypatch.setattr(transcript_runner, "missing_requirements", lambda _req: ["scheduling"])
    monkeypatch.setattr(
        transcript_runner,
        "load_fixture",
        lambda _id: pytest.fail("gated scenario must not load a fixture"),
    )
    scenario = _scenario("s_gated", feature="scheduling", requires=["scheduling"])
    failed = _run_matrix([scenario], live=False)
    out = capsys.readouterr().out
    assert failed is False
    assert "SKIP  s_gated" in out
    assert "PASS  s_gated" not in out


def test_missing_fixture_is_a_hard_error_not_a_silent_skip(monkeypatch, capsys):
    def _raise(_id):
        raise FixtureNotFoundError("no fixture")

    monkeypatch.setattr(transcript_runner, "load_fixture", _raise)
    failed = _run_matrix([_scenario("s_missing")], live=False)
    out = capsys.readouterr().out
    assert failed is True  # a missing fixture MUST fail the gate
    assert "ERROR s_missing" in out
    assert "SKIP" not in out


def test_matrix_is_deterministic_across_repeated_runs(monkeypatch, capsys):
    monkeypatch.setattr(transcript_runner, "load_fixture", lambda _id: _PASSING_FIXTURE)
    scenarios = [_scenario("s_a"), _scenario("s_b")]
    _run_matrix(scenarios, live=False)
    first = capsys.readouterr().out
    _run_matrix(scenarios, live=False)
    second = capsys.readouterr().out
    assert first == second


# --- Canary decision logic (hermetic) -----------------------------------------------


def test_canary_that_fails_structurally_passes_the_suite(monkeypatch, capsys):
    monkeypatch.setattr(transcript_runner, "load_fixture", lambda _id: _FAILING_FIXTURE)
    canary = _scenario("c_good", canary=True, canary_layer="structural")
    failed = _run_canaries([canary])
    out = capsys.readouterr().out
    assert failed is False
    assert "PASS  c_good  (failed as expected" in out


def test_canary_that_does_not_fail_is_flagged_as_harness_bug(monkeypatch, capsys):
    # The anti-vacuity guard: a canary fixture that structurally PASSES means the
    # deliberate defect stopped being caught — the runner must fail the suite.
    monkeypatch.setattr(transcript_runner, "load_fixture", lambda _id: _PASSING_FIXTURE)
    canary = _scenario("c_bad", canary=True, canary_layer="structural")
    failed = _run_canaries([canary])
    out = capsys.readouterr().out
    assert failed is True
    assert "did NOT fail" in out


def test_eval_layer_canary_is_skipped_by_structural_runner(monkeypatch, capsys):
    monkeypatch.setattr(
        transcript_runner,
        "load_fixture",
        lambda _id: pytest.fail("eval-layer canary must not be structurally checked"),
    )
    canary = _scenario("c_eval", canary=True, canary_layer="eval")
    failed = _run_canaries([canary])
    out = capsys.readouterr().out
    assert failed is False
    assert "SKIP  c_eval" in out
    assert "eval-layer canary" in out


def test_gated_canary_skips(monkeypatch, capsys):
    monkeypatch.setattr(transcript_runner, "missing_requirements", lambda _req: ["visual"])
    canary = _scenario(
        "c_gated", canary=True, canary_layer="structural", feature="visual", requires=["visual"]
    )
    failed = _run_canaries([canary])
    out = capsys.readouterr().out
    assert failed is False
    assert "SKIP  c_gated" in out


def test_missing_canary_fixture_is_a_hard_error(monkeypatch, capsys):
    def _raise(_id):
        raise FixtureNotFoundError("no fixture")

    monkeypatch.setattr(transcript_runner, "load_fixture", _raise)
    canary = _scenario("c_missing", canary=True, canary_layer="structural")
    failed = _run_canaries([canary])
    assert failed is True
    assert "ERROR c_missing" in capsys.readouterr().out
