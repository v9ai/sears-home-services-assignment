"""Prompt static asserts for the scheduling contract (same pattern as the
latency-engineering acknowledge-before-tools assert): live-run evidence
(2026-07-09, booking-session-attribution manual gate) showed the model calling
`book_appointment` with an invented slot id — the UUIDs from `find_technicians`
must be echoed verbatim, and the prompt is the only place that rule can live
(the frozen tool signature can't carry it)."""

from __future__ import annotations

from app.agent.prompts import SCHEDULING_CONTRACT, build_system_prompt
from app.contracts import CaseFile


def test_scheduling_contract_pins_exact_slot_id_echo():
    assert "exact `slot_id`" in SCHEDULING_CONTRACT
    assert "verbatim" in SCHEDULING_CONTRACT
    # The short-ref escape hatch (2026-07-09-slot-reference-robustness): live models
    # pass ordinals, so the prompt must sanction the `ref` form it will actually use.
    assert "`slot_1`" in SCHEDULING_CONTRACT
    # Recovery path: a lost id means re-fetching, not guessing.
    assert "call `find_technicians` again" in SCHEDULING_CONTRACT


def test_system_prompt_carries_the_scheduling_contract():
    prompt = build_system_prompt(CaseFile())
    assert "exact `slot_id`" in prompt


def test_scheduling_contract_reuses_captured_zip_never_reasks():
    # Booking must not re-ask for the zip the case file already holds — the never-re-ask
    # non-negotiable, restated at the point it's most tempting to violate.
    assert "reuse the case file's `customer.zip`" in SCHEDULING_CONTRACT
    assert "never re-ask for the zip" in SCHEDULING_CONTRACT


def test_scheduling_contract_caps_options_at_three():
    # A voice call can't recite a long list — the "at most 3" cap keeps the turn spoken.
    assert "at most 3 options" in SCHEDULING_CONTRACT


def test_scheduling_contract_requires_explicit_confirmation_before_booking():
    assert "explicit" in SCHEDULING_CONTRACT
    assert "book_appointment" in SCHEDULING_CONTRACT
    # A read-back of technician + date + time precedes the yes.
    assert "read back" in SCHEDULING_CONTRACT


def test_scheduling_contract_pins_find_technicians_signature():
    assert "find_technicians(zip, appliance_type, window?)" in SCHEDULING_CONTRACT


def test_scheduling_contract_handles_slot_taken_without_silent_retry():
    # Live evidence drove this rule: a taken slot must surface alternatives, never a
    # silent re-book of the same slot.
    assert "slot_taken" in SCHEDULING_CONTRACT
    assert "alternatives" in SCHEDULING_CONTRACT
    assert "never silently retry" in SCHEDULING_CONTRACT


def test_scheduling_contract_reads_back_appointment_id_on_confirm():
    assert "confirmed" in SCHEDULING_CONTRACT
    assert "appointment_id" in SCHEDULING_CONTRACT


def test_scheduling_contract_requires_issue_summary_to_name_the_appliance():
    # book_appointment infers the appliance from issue_summary and errors without it.
    assert "issue_summary" in SCHEDULING_CONTRACT
    assert "must name the appliance" in SCHEDULING_CONTRACT


def test_captured_zip_appears_in_the_prompt_so_booking_can_reuse_it():
    case_file = CaseFile()
    case_file.customer.zip = "60614"
    case_file.appliance_type = "washer"
    prompt = build_system_prompt(case_file)
    # Both facts find_technicians needs are present in-context — no re-ask required.
    assert "60614" in prompt
    assert "washer" in prompt


# --- Booking-finalization drift guards (task #21) -----------------------------------
# Live-observed 2026-07-10: under a natural caller the agent looped on confirmation and
# re-ran find_technicians after an explicit slot acceptance instead of booking. These
# lock the prompt directives that make the accept→book transition one-way.


def test_acceptance_converts_to_a_single_book_call_in_one_step():
    # The core fix: an explicit acceptance IS the confirmation, and the very next action
    # must be a single book_appointment — not another confirmation round.
    assert "very next action must be a single" in SCHEDULING_CONTRACT
    assert "book_appointment" in SCHEDULING_CONTRACT
    # An acceptance does not require a second yes.
    assert "second explicit" in SCHEDULING_CONTRACT


def test_prompt_forbids_re_searching_after_an_acceptance():
    # The exact loop we saw live: re-running find_technicians / re-asking "which day?"
    # after the caller already accepted a slot.
    assert "re-run `find_technicians`" in SCHEDULING_CONTRACT
    assert "restarts the booking" in SCHEDULING_CONTRACT
    # The lost-list re-fetch escape hatch must be explicitly NOT for plain acceptances.
    assert "never in reaction to a plain acceptance" in SCHEDULING_CONTRACT


def test_prompt_requires_zip_before_find_technicians():
    # Secondary oddity from the live run: find_technicians fired before a zip was
    # captured, returning no technicians.
    assert "Zip is required before `find_technicians`" in SCHEDULING_CONTRACT
    assert "Never call `find_technicians` without a zip" in SCHEDULING_CONTRACT


def test_prompt_requires_persisting_the_zip_into_the_case_file():
    # Live re-run (evals-live, 2026-07-10): the model passed the zip only as a
    # find_technicians ARG and never called update_case_file, so the rebuilt prompt on
    # the acceptance turn saw an empty zip and re-asked — starving the FINALIZE step.
    # The contract must direct persistence via update_case_file, in the same response.
    assert "update_case_file(customer_zip=" in SCHEDULING_CONTRACT
    assert "in the SAME response" in SCHEDULING_CONTRACT
    # And name the failure it prevents, so the instruction isn't later trimmed as noise.
    assert "forgotten next turn" in SCHEDULING_CONTRACT


def test_finalization_directives_reach_the_system_prompt():
    prompt = build_system_prompt(CaseFile())
    assert "very next action must be a single" in prompt
    assert "Never call `find_technicians` without a zip" in prompt


# --- Offered-slot retention (task #21, iteration 4) ---------------------------------
# Live re-run showed the FINALIZE step starved of state one level up from the zip: the
# slots find_technicians offered weren't retained, so the acceptance turn's rebuilt prompt
# had "no record of offering a specific slot" and the model re-searched. The offered slots
# are now threaded into the prompt so an acceptance maps to a ref without re-searching.

_OFFERED = [
    {
        "ref": "slot_1",
        "technician": "Marcus Bell",
        "slot_id": "11111111-1111-1111-1111-111111111111",
        "starts_at": "2026-07-11T15:00:00",
        "ends_at": "2026-07-11T17:00:00",
    },
    {
        "ref": "slot_2",
        "technician": "Sam Lee",
        "slot_id": "22222222-2222-2222-2222-222222222222",
        "starts_at": "2026-07-12T09:00:00",
        "ends_at": "2026-07-12T11:00:00",
    },
]


def test_offered_slots_are_listed_with_refs_and_times_in_the_prompt():
    prompt = build_system_prompt(CaseFile(appliance_type="dishwasher"), _OFFERED)
    # Each offered slot appears with its ref, technician, and time so the model can map
    # a spoken acceptance to a concrete ref.
    assert "slot_1" in prompt and "Marcus Bell" in prompt and "2026-07-11T15:00:00" in prompt
    assert "slot_2" in prompt and "Sam Lee" in prompt


def test_offered_slots_prompt_forbids_re_searching_and_points_to_book():
    prompt = build_system_prompt(CaseFile(), _OFFERED)
    assert "ALREADY offered" in prompt
    assert "do NOT call `find_technicians` again" in prompt
    assert "book_appointment" in prompt


def test_no_offered_slots_means_no_slots_section():
    # Turns with no live offer (or the default call) must not grow a slots section.
    prompt = build_system_prompt(CaseFile(appliance_type="dishwasher"))
    assert "ALREADY offered" not in prompt


def test_prompt_requires_name_and_email_before_booking():
    # Task #27: book_appointment now refuses without the caller's name+email, so the
    # contract must tell the model to collect + confirm + persist them before finalize.
    assert "name AND email must be on file" in SCHEDULING_CONTRACT
    assert "update_case_file(customer_name=..., customer_email=...)" in SCHEDULING_CONTRACT
    # Reuses the existing spell-back-the-email discipline.
    assert "spell the email back" in SCHEDULING_CONTRACT


def test_offered_slots_do_not_break_the_compact_case_file_invariant():
    # Guard the P1-2 cost invariant (tests/latency): the compact case-file JSON is still a
    # substring and the pretty form still absent, even with the slots section appended.
    case_file = CaseFile(appliance_type="washer")
    prompt = build_system_prompt(case_file, _OFFERED)
    assert case_file.model_dump_json() in prompt
    assert case_file.model_dump_json(indent=2) not in prompt
