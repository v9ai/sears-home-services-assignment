"""Hermetic guards for the booking-quality bench (2026-07-10-booking-quality-loop):
the reply policy's decision table, the per-scenario scoring rules, and the report
comparator. No DB, no LLM — the policy is the deterministic half of the adaptive
drives, so its branches are pinned here exactly."""

from __future__ import annotations

from evals.adaptive_driver import AdaptiveScenario, PolicyState, opening_line, reply_policy
from scripts.booking_quality_bench import SCENARIOS, compare, score_scenario

BOOKING = AdaptiveScenario(id="t", appliance="dishwasher", symptom="won't drain", zip="60601")
SAFETY = AdaptiveScenario(
    id="ts",
    appliance="oven",
    symptom="clicks but won't ignite",
    zip="60642",
    safety_line="I can smell gas near the oven.",
)
NO_TECH = AdaptiveScenario(
    id="tn", appliance="dishwasher", symptom="smells burnt", zip="60614", expect_no_tech=True
)


# --- reply policy decision table -----------------------------------------------------
def test_booked_confirmation_terminates():
    assert reply_policy("You're all set: Marcus Bell is booked.", BOOKING, PolicyState()) is None
    assert reply_policy("Your confirmation number is APT-1042.", BOOKING, PolicyState()) is None


def test_fact_question_outranks_confirmation_wording():
    # "confirm your name/zip/email" is a FACT question — must answer facts, not "yes book it".
    reply = reply_policy(
        "Could you please confirm your name, zip code, and email for the booking?",
        BOOKING,
        PolicyState(),
    )
    assert BOOKING.zip in reply or "Jamie" in reply
    assert "book it now" not in reply


def test_readback_confirmation_gets_explicit_yes():
    state = PolicyState()
    reply = reply_policy(
        "Just to confirm, Marcus Bell on July 10th at 9 AM for your dishwasher. Is that correct?",
        BOOKING,
        state,
    )
    assert reply.startswith("Yes")
    assert state.accepted_slot


def test_slot_offer_takes_first_option():
    reply = reply_policy(
        "Marcus Bell has three slots on July 10th. Which time works best for you?",
        BOOKING,
        PolicyState(),
    )
    assert "first option" in reply.lower()


def test_lost_list_points_back_at_the_tool():
    reply = reply_policy(
        "I don't see the list of available slots right now.", BOOKING, PolicyState()
    )
    assert "find_technicians" in reply


def test_slot_taken_accepts_the_reoffer():
    reply = reply_policy(
        "I'm sorry, that slot is no longer available. The next opening is Friday.",
        BOOKING,
        PolicyState(),
    )
    assert "next available" in reply.lower() or "works" in reply.lower()


def test_troubleshooting_drift_redirects_to_booking():
    reply = reply_policy(
        "Let's start by checking the drain filter at the bottom.", BOOKING, PolicyState()
    )
    assert "technician appointment" in reply


def test_safety_line_injected_once_then_normal_flow():
    state = PolicyState()
    first = reply_policy("What's going on with your oven?", SAFETY, state)
    assert "gas" in first
    second = reply_policy(
        "Please shut it off. Shall I book a technician? Is that correct?", SAFETY, state
    )
    assert second.startswith("Yes")


def test_no_coverage_terminates_when_agent_owns_the_gap():
    assert (
        reply_policy(
            "I'm sorry, there are no available technicians for dishwashers in your area.",
            NO_TECH,
            PolicyState(),
        )
        is None
    )


def test_generic_fallback_counts_nudges():
    state = PolicyState()
    reply_policy("Thank you for calling. Anything else on your mind today.", BOOKING, state)
    assert state.nudges == 1


def test_opening_lines_differ_by_disclosure_mode():
    assert BOOKING.zip in opening_line(BOOKING)  # upfront reveals everything
    drip = AdaptiveScenario(
        id="d", appliance="washer", symptom="shakes", zip="60614", upfront=False
    )
    line = opening_line(drip)
    assert drip.zip not in line and "washer" in line


# --- scoring rules -------------------------------------------------------------------
def _drive(**overrides):
    base = {
        "turns_used": 3,
        "converged": True,
        "reasked_fields": [],
        "nudges": 0,
        "safety_flag": False,
        "wiretap_calls": [],
    }
    base.update(overrides)
    return base


def test_booking_scenario_passes_on_clean_booked_drive():
    verdict = score_scenario(
        AdaptiveScenario(id="happy_upfront", appliance="dishwasher", symptom="s", zip="60601"),
        _drive(),
        booked=True,
    )
    assert verdict["pass"]


def test_booking_scenario_fails_without_booking_and_names_why():
    verdict = score_scenario(
        AdaptiveScenario(id="happy_upfront", appliance="dishwasher", symptom="s", zip="60601"),
        _drive(),
        booked=False,
    )
    assert not verdict["pass"]
    assert any("no booking" in r for r in verdict["reasons"])


def test_reasks_and_turn_budget_fail_the_scenario():
    verdict = score_scenario(
        AdaptiveScenario(
            id="happy_upfront", appliance="dishwasher", symptom="s", zip="60601", turn_budget=4
        ),
        _drive(turns_used=5, reasked_fields=["customer.zip"]),
        booked=True,
    )
    assert not verdict["pass"]
    assert len(verdict["reasons"]) == 2


def test_no_coverage_scenario_fails_if_it_books():
    verdict = score_scenario(NO_TECH, _drive(), booked=True)
    assert not verdict["pass"]


def test_safety_scenario_requires_the_flag():
    assert not score_scenario(SAFETY, _drive(), booked=False)["pass"]
    assert score_scenario(SAFETY, _drive(safety_flag=True), booked=False)["pass"]


def test_conflict_scenario_requires_slot_taken_to_have_surfaced():
    scenario = AdaptiveScenario(
        id="slot_conflict", appliance="oven", symptom="s", zip="60642", expect_conflict=True
    )
    calls = [
        {"tool": "book_appointment", "slot_id": "slot_1", "status": "slot_taken"},
        {"tool": "book_appointment", "slot_id": "slot_2", "status": "confirmed"},
    ]
    assert score_scenario(scenario, _drive(wiretap_calls=calls), booked=True)["pass"]
    assert not score_scenario(scenario, _drive(), booked=True)["pass"]


def test_tool_exception_fails_any_scenario():
    verdict = score_scenario(
        SAFETY,
        _drive(safety_flag=True, wiretap_calls=[{"tool": "book_appointment", "exception": "X"}]),
        booked=False,
    )
    assert not verdict["pass"]


# --- comparator + matrix pins --------------------------------------------------------
def test_compare_flags_pass_to_fail_regression_only():
    before = {
        "scenarios": [{"scenario_id": "a", "pass": True}, {"scenario_id": "b", "pass": False}]
    }
    after_ok = {
        "scenarios": [{"scenario_id": "a", "pass": True}, {"scenario_id": "b", "pass": False}]
    }
    after_bad = {
        "scenarios": [{"scenario_id": "a", "pass": False}, {"scenario_id": "b", "pass": True}]
    }
    assert compare(before, after_ok)[0]
    assert not compare(before, after_bad)[0]


def test_scenario_matrix_is_pinned():
    ids = [s.id for s in SCENARIOS]
    assert ids == [
        "happy_upfront",
        "drip_fed",
        "reask_trap",
        "no_coverage",
        "slot_conflict",
        "safety_interrupt",
    ]
    by_id = {s.id: s for s in SCENARIOS}
    assert by_id["no_coverage"].expect_no_tech
    assert by_id["safety_interrupt"].safety_line
    assert not by_id["drip_fed"].upfront
    # every bench customer email is cleanup-taggable
    assert all(s.email.endswith("@bench.example.test") for s in SCENARIOS)
