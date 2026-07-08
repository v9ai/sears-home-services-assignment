"""Structural-assertion unit tests, isolated from the real fixture files (protects
against fixture-authoring mistakes being the only test signal)."""

from __future__ import annotations

from evals.assertions import check_structural_assertions
from evals.scenarios.schema import Scenario


def _scenario(**assert_overrides):
    data = {
        "id": "unit_test_scenario",
        "feature": "core",
        "turns": [{"caller": "hi"}],
        "assert": {
            "facts": {},
            "no_reask": [],
            "safety_interrupt": False,
            "booking_row": False,
            **assert_overrides,
        },
    }
    return Scenario.model_validate(data)


def test_facts_mismatch_is_reported():
    scenario = _scenario(facts={"appliance_type": "washer"})
    fixture = {"case_file": {"appliance_type": "dryer"}, "flags": {}}
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    assert any("appliance_type" in f for f in result.failures)


def test_missing_fact_is_reported():
    scenario = _scenario(facts={"appliance_type": "washer"})
    fixture = {"case_file": {}, "flags": {}}
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    assert any("missing from case file" in f for f in result.failures)


def test_nested_fact_path_resolves_through_dicts_and_lists():
    scenario = _scenario(facts={"customer.zip": "60614", "symptoms.0.error_code": "5E"})
    fixture = {
        "case_file": {
            "customer": {"zip": "60614"},
            "symptoms": [{"error_code": "5E"}],
        },
        "flags": {},
    }
    result = check_structural_assertions(scenario, fixture)
    assert result.ok


def test_no_reask_violation_is_reported():
    scenario = _scenario(no_reask=["customer.zip"])
    fixture = {
        "case_file": {"customer": {"zip": "60614"}},
        "flags": {"reasked_fields": ["customer.zip"]},
    }
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    assert any("re-asked" in f for f in result.failures)


def test_no_reask_satisfied_when_field_not_in_reasked_list():
    scenario = _scenario(no_reask=["customer.zip"])
    fixture = {"case_file": {"customer": {"zip": "60614"}}, "flags": {"reasked_fields": []}}
    result = check_structural_assertions(scenario, fixture)
    assert result.ok


def test_safety_interrupt_mismatch_is_reported():
    scenario = _scenario(safety_interrupt=True)
    fixture = {"case_file": {}, "flags": {"safety_interrupt": False}}
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok


def test_booking_row_mismatch_is_reported():
    scenario = _scenario(booking_row=True)
    fixture = {"case_file": {}, "flags": {"booking_row": False}}
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok


def test_all_pass_when_expectations_match():
    scenario = _scenario(
        facts={"appliance_type": "washer"},
        safety_interrupt=True,
        booking_row=True,
        no_reask=["customer.zip"],
    )
    fixture = {
        "case_file": {"appliance_type": "washer", "customer": {"zip": "60614"}},
        "flags": {"safety_interrupt": True, "booking_row": True, "reasked_fields": []},
    }
    result = check_structural_assertions(scenario, fixture)
    assert result.ok
    assert result.failures == []
