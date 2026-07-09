"""Slot reference robustness (2026-07-09-slot-reference-robustness).

Live evidence: the web agent's model passes `slot_id='slot_1'` instead of copying
UUIDs from `find_technicians`' payload. The tool layer now labels offers with short
`ref`s (per ambient session) and `book_appointment` resolves them — UUIDs stay
first-class.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.agent.state import current_session_id
from app.contracts import Customer
from app.db.matching import session_scope
from app.db.models_scheduling import Appointment
from app.tools.scheduling_tools import (
    _offered_slot_refs,
    _resolve_slot_reference,
    book_appointment,
    find_technicians,
)

from .factories import make_slot, make_technician


async def _seed(zip_code: str = "60601", *, days: int = 1) -> uuid.UUID:
    async with session_scope() as session:
        tech_id = await make_technician(session, zips=(zip_code,), specialties=("washer",))
        slot_id = await make_slot(session, tech_id, datetime.now(UTC) + timedelta(days=days))
        await session.commit()
    return slot_id


async def test_find_technicians_labels_offers_with_refs():
    slot_id = await _seed()
    token = current_session_id.set(None)
    try:
        result = json.loads(await find_technicians("60601", "washer"))
    finally:
        current_session_id.reset(token)

    slots = result["technicians"][0]["slots"]
    assert slots[0]["ref"] == "slot_1"
    assert slots[0]["slot_id"] == str(slot_id)
    assert _offered_slot_refs[None]["slot_1"] == str(slot_id)


async def test_booking_via_short_ref_resolves_and_books():
    slot_id = await _seed()
    token = current_session_id.set(None)
    try:
        await find_technicians("60601", "washer")
        result = json.loads(
            await book_appointment("slot_1", Customer(name="Jamie Rivera"), "Washer won't spin")
        )
    finally:
        current_session_id.reset(token)

    assert result["status"] == "confirmed"
    async with session_scope() as session:
        appt = (
            await session.execute(select(Appointment).where(Appointment.slot_id == slot_id))
        ).scalar_one()
        assert appt.status == "confirmed"


async def test_ref_normalization_variants():
    session_key = None
    token = current_session_id.set(session_key)
    try:
        _offered_slot_refs[session_key] = {"slot_2": "a" * 36}
        assert _resolve_slot_reference("slot_2") == "a" * 36
        assert _resolve_slot_reference("2") == "a" * 36
        assert _resolve_slot_reference("option 2") == "a" * 36
        assert _resolve_slot_reference("Option_2") == "a" * 36
        assert _resolve_slot_reference("slot 2") == "a" * 36
        assert _resolve_slot_reference("slot_9") is None
        assert _resolve_slot_reference("garbage") is None
    finally:
        _offered_slot_refs.pop(session_key, None)
        current_session_id.reset(token)


async def test_refs_are_session_scoped():
    session_a, session_b = uuid.uuid4(), uuid.uuid4()
    _offered_slot_refs[session_a] = {"slot_1": "uuid-for-a"}
    try:
        token = current_session_id.set(session_b)
        try:
            assert _resolve_slot_reference("slot_1") is None  # B never got an offer
        finally:
            current_session_id.reset(token)

        token = current_session_id.set(session_a)
        try:
            assert _resolve_slot_reference("slot_1") == "uuid-for-a"
        finally:
            current_session_id.reset(token)
    finally:
        _offered_slot_refs.pop(session_a, None)


async def test_unknown_ref_returns_structured_error_pointing_at_find():
    token = current_session_id.set(None)
    _offered_slot_refs.pop(None, None)  # no offers cached for this session
    try:
        result = json.loads(
            await book_appointment("slot_1", Customer(name="Jamie Rivera"), "Washer broken")
        )
    finally:
        current_session_id.reset(token)
    assert result["status"] == "error"
    assert "find_technicians" in result["message"]


async def test_customer_dict_is_coerced_like_the_live_tool_loop_passes_it():
    """The LlamaIndex tool loop hands nested object args over as raw dicts — every live
    web-channel booking raised `AttributeError: 'dict' object has no attribute 'email'`
    until the tool boundary coerced them (live evidence 2026-07-09)."""
    slot_id = await _seed()
    token = current_session_id.set(None)
    _offered_slot_refs.pop(None, None)
    try:
        result = json.loads(
            await book_appointment(
                str(slot_id),
                {"name": "Jamie Rivera", "zip": "60601", "email": "jamie@example.test"},
                "Washer won't spin",
            )
        )
    finally:
        current_session_id.reset(token)
    assert result["status"] == "confirmed"


async def test_uuid_slot_ids_still_first_class():
    slot_id = await _seed()
    token = current_session_id.set(None)
    _offered_slot_refs.pop(None, None)  # no ref cache needed for the UUID path
    try:
        result = json.loads(
            await book_appointment(str(slot_id), Customer(name="Jamie Rivera"), "Washer won't spin")
        )
    finally:
        current_session_id.reset(token)
    assert result["status"] == "confirmed"
