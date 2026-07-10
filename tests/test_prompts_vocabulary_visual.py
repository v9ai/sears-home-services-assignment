"""Knowledge-vocabulary and image-upload-contract prompt guards (bugfix-loop T8).

Two Tier-relevant prompt surfaces had zero assertions: `_knowledge_vocabulary`
(the Tier-1 guard that stops the model inventing symptom keys — neither branch's
output was checked anywhere) and the entire IMAGE_UPLOAD_CONTRACT (Tier-3 email
spell-back + upload tool directives — never verified to reach the prompt).
"""

from __future__ import annotations

import pytest

from app.agent.prompts import build_system_prompt
from app.contracts import CaseFile
from app.knowledge.loader import symptom_keys_for

APPLIANCES = ("washer", "dryer", "refrigerator", "dishwasher", "oven", "hvac")


# --- _knowledge_vocabulary: identified branch ---------------------------------


@pytest.mark.parametrize("appliance", APPLIANCES)
def test_identified_appliance_prompt_names_its_symptom_keys(appliance: str) -> None:
    prompt = build_system_prompt(CaseFile(appliance_type=appliance))
    assert f"Known symptom_key values for {appliance}:" in prompt
    for key in symptom_keys_for(appliance):
        assert key in prompt, f"symptom_key {key!r} missing from the {appliance} prompt"


def test_identified_prompt_does_not_carry_the_unidentified_text() -> None:
    prompt = build_system_prompt(CaseFile(appliance_type="washer"))
    assert "Appliance not yet identified" not in prompt


# --- _knowledge_vocabulary: unidentified branch --------------------------------


def test_unidentified_prompt_directs_to_identify_and_lists_supported_types() -> None:
    prompt = build_system_prompt(CaseFile())
    assert "Appliance not yet identified — call identify_appliance first." in prompt
    for appliance in APPLIANCES:
        assert appliance in prompt
    assert "Known symptom_key values" not in prompt


# --- IMAGE_UPLOAD_CONTRACT ------------------------------------------------------


def test_image_upload_contract_reaches_the_prompt_with_its_directives() -> None:
    prompt = build_system_prompt(CaseFile())
    # Spell-back gate: wrong address means the link never arrives.
    assert "spell it back character by character" in prompt
    assert '"yes, that\'s right"' in prompt
    # Tool directives by exact name (the model calls what the prompt names).
    assert "send_image_upload_link(email)" in prompt
    assert "check_image_analysis()" in prompt
    # Email reuse rule (never-re-ask applied to the email field).
    assert "Reuse the case file's `customer.email`" in prompt
    # Findings folded into guidance, not read verbatim.
    assert "don't just read it" in prompt


def test_image_upload_contract_offers_email_only_never_sms() -> None:
    # SMS is not implemented (email only; spec defers SMS), so the prompt must never
    # promise a text message the agent can't send — offer email exclusively.
    prompt = build_system_prompt(CaseFile())
    assert "offer to email them a secure link" in prompt
    assert "never offer to text or SMS the link" in prompt
    assert "text or email them" not in prompt


def test_image_upload_contract_present_for_every_case_file_state() -> None:
    # The contract is unconditional — identified, safety-flagged, or fresh.
    for case_file in (
        CaseFile(),
        CaseFile(appliance_type="dryer"),
        CaseFile(appliance_type="oven", safety_flag=True),
    ):
        assert "Photos of the appliance:" in build_system_prompt(case_file)
