"""Core tool unit tests: case-file mutation/merge behavior (validation.md gate 1).

Each test sets `app.agent.state.current_case_file` directly inside the test coroutine
(rather than in a fixture) so the contextvar is unambiguously visible to the tool call
that follows in the same async context.
"""

from __future__ import annotations

import pytest

from app.agent.state import current_case_file
from app.contracts import CaseFile
from app.tools import core_tools


def _bind(case_file: CaseFile):
    return current_case_file.set(case_file)


@pytest.mark.asyncio
async def test_identify_appliance_sets_type() -> None:
    case_file = CaseFile()
    token = _bind(case_file)
    try:
        result = await core_tools.identify_appliance("Washer")
    finally:
        current_case_file.reset(token)
    assert case_file.appliance_type == "washer"
    assert "washer" in result


@pytest.mark.asyncio
async def test_identify_appliance_rejects_unknown_type() -> None:
    case_file = CaseFile()
    token = _bind(case_file)
    try:
        result = await core_tools.identify_appliance("toaster")
    finally:
        current_case_file.reset(token)
    assert case_file.appliance_type is None
    assert "not a supported appliance" in result


@pytest.mark.asyncio
async def test_record_symptom_appends_without_clobbering_existing() -> None:
    case_file = CaseFile()
    token = _bind(case_file)
    try:
        await core_tools.record_symptom("grinding noise", onset="yesterday", error_code="E3")
        await core_tools.record_symptom("won't spin")
    finally:
        current_case_file.reset(token)
    assert len(case_file.symptoms) == 2
    assert case_file.symptoms[0].description == "grinding noise"
    assert case_file.symptoms[0].error_code == "E3"
    assert case_file.symptoms[1].description == "won't spin"


@pytest.mark.asyncio
async def test_get_troubleshooting_steps_records_steps_given() -> None:
    case_file = CaseFile(appliance_type="washer")
    token = _bind(case_file)
    try:
        result = await core_tools.get_troubleshooting_steps("washer", "loud_noise")
    finally:
        current_case_file.reset(token)
    assert case_file.steps_given  # non-empty
    assert not case_file.safety_flag
    assert "1." in result


@pytest.mark.asyncio
async def test_get_troubleshooting_steps_safety_tree_sets_safety_flag() -> None:
    case_file = CaseFile(appliance_type="oven")
    token = _bind(case_file)
    try:
        result = await core_tools.get_troubleshooting_steps("oven", "safety_gas_smell")
    finally:
        current_case_file.reset(token)
    assert case_file.safety_flag is True
    assert "SAFETY ESCALATION" in result


@pytest.mark.asyncio
async def test_get_troubleshooting_steps_unknown_symptom_key_is_safe() -> None:
    case_file = CaseFile(appliance_type="washer")
    token = _bind(case_file)
    try:
        result = await core_tools.get_troubleshooting_steps("washer", "nonexistent")
    finally:
        current_case_file.reset(token)
    assert "Unknown symptom_key" in result
    assert case_file.steps_given == []


@pytest.mark.asyncio
async def test_update_case_file_merges_customer_fields_without_overwriting_others() -> None:
    case_file = CaseFile()
    token = _bind(case_file)
    try:
        await core_tools.update_case_file(customer_name="Jamie")
        await core_tools.update_case_file(customer_zip="90210")
    finally:
        current_case_file.reset(token)
    assert case_file.customer.name == "Jamie"
    assert case_file.customer.zip == "90210"
    assert case_file.customer.email is None


@pytest.mark.asyncio
async def test_update_case_file_normalizes_email() -> None:
    case_file = CaseFile()
    token = _bind(case_file)
    try:
        result = await core_tools.update_case_file(customer_email="Jamie at example dot com")
    finally:
        current_case_file.reset(token)
    assert case_file.customer.email == "jamie@example.com"
    assert "customer.email=jamie@example.com" in result


@pytest.mark.asyncio
async def test_update_case_file_rejects_invalid_email_without_overwriting() -> None:
    case_file = CaseFile()
    case_file.customer.email = "jamie@example.com"
    token = _bind(case_file)
    try:
        result = await core_tools.update_case_file(customer_email="not an email")
    finally:
        current_case_file.reset(token)
    assert case_file.customer.email == "jamie@example.com"
    assert "not saved" in result


@pytest.mark.asyncio
async def test_update_case_file_no_fields_is_a_noop() -> None:
    case_file = CaseFile()
    token = _bind(case_file)
    try:
        result = await core_tools.update_case_file()
    finally:
        current_case_file.reset(token)
    assert "unchanged" in result
