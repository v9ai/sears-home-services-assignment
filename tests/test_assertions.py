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


def test_safety_interrupt_false_expectation_catches_a_spurious_flag():
    # Reverse direction of the existing test: expecting NO interrupt must fail if the
    # fixture recorded one (guards a canary that must NOT trip safety).
    scenario = _scenario(safety_interrupt=False)
    fixture = {"case_file": {}, "flags": {"safety_interrupt": True}}
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    assert any("safety_interrupt = True" in f for f in result.failures)


def test_booking_row_false_expectation_catches_a_spurious_booking():
    scenario = _scenario(booking_row=False)
    fixture = {"case_file": {}, "flags": {"booking_row": True}}
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    assert any("booking_row = True" in f for f in result.failures)


def test_all_four_assertion_kinds_accumulate_into_one_report():
    # The checker must return EVERY defect, not short-circuit on the first — a runner
    # relies on the full list.
    scenario = _scenario(
        facts={"appliance_type": "washer", "brand": "LG"},
        no_reask=["customer.zip"],
        safety_interrupt=True,
        booking_row=True,
    )
    fixture = {
        "case_file": {"appliance_type": "dryer", "customer": {"zip": "60614"}},
        "flags": {
            "safety_interrupt": False,
            "booking_row": False,
            "reasked_fields": ["customer.zip"],
        },
    }
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    # appliance mismatch + brand missing + zip re-asked + safety + booking = 5 failures.
    assert len(result.failures) == 5


def test_missing_flags_block_is_treated_as_all_defaults():
    # A fixture with no `flags` key must not crash; absent flags read as False/empty.
    scenario = _scenario(safety_interrupt=False, booking_row=False)
    result = check_structural_assertions(scenario, {"case_file": {}})
    assert result.ok


def test_missing_case_file_reports_missing_facts_not_crash():
    scenario = _scenario(facts={"appliance_type": "washer"})
    result = check_structural_assertions(scenario, {"flags": {}})
    assert not result.ok
    assert any("missing from case file" in f for f in result.failures)


def test_list_index_out_of_range_is_a_missing_fact_not_a_crash():
    scenario = _scenario(facts={"symptoms.5.error_code": "5E"})
    fixture = {"case_file": {"symptoms": [{"error_code": "5E"}]}, "flags": {}}
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    assert any("missing from case file" in f for f in result.failures)


def test_non_integer_index_into_a_list_is_missing_not_a_crash():
    # A dotted path that indexes a list with a non-digit segment must resolve to MISSING
    # rather than raising (protects the runner from a mis-authored assertion path).
    scenario = _scenario(facts={"symptoms.first.error_code": "5E"})
    fixture = {"case_file": {"symptoms": [{"error_code": "5E"}]}, "flags": {}}
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    assert any("missing from case file" in f for f in result.failures)


def test_negative_list_index_resolves():
    scenario = _scenario(facts={"symptoms.-1.error_code": "OE"})
    fixture = {
        "case_file": {"symptoms": [{"error_code": "5E"}, {"error_code": "OE"}]},
        "flags": {},
    }
    assert check_structural_assertions(scenario, fixture).ok


def test_descending_into_a_scalar_is_missing_not_a_crash():
    # Path expects a nested dict but the case file holds a scalar there.
    scenario = _scenario(facts={"appliance_type.brand": "LG"})
    fixture = {"case_file": {"appliance_type": "washer"}, "flags": {}}
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    assert any("missing from case file" in f for f in result.failures)


def test_falsey_expected_value_still_compared_not_skipped():
    # An expected value of 0/"" must be checked, not treated as "no expectation".
    scenario = _scenario(facts={"symptoms.0.count": 0})
    fixture = {"case_file": {"symptoms": [{"count": 3}]}, "flags": {}}
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    assert any("count" in f for f in result.failures)


def test_multiple_no_reask_fields_each_reported_independently():
    scenario = _scenario(no_reask=["customer.zip", "customer.email"])
    fixture = {
        "case_file": {"customer": {"zip": "60614", "email": "x@y.z"}},
        "flags": {"reasked_fields": ["customer.zip", "customer.email"]},
    }
    result = check_structural_assertions(scenario, fixture)
    assert not result.ok
    assert sum("re-asked" in f for f in result.failures) == 2
