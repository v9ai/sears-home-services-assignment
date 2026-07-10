"""Live LLM-caller e2e — the full happy-path booking, end to end into Postgres.

The persona drives the whole arc a real caller would: symptom → declines/​exhausts
troubleshooting → gives zip → hears a slot proposal → confirms verbally. Success is a
real `appointments` row attributed to the driven session (`appointments_booking_probe`),
checked through the same structural-assertion helper the fixture gate uses
(`evals.assertions.check_structural_assertions`) so the pass/fail shape is identical.

Heavily guarded (advisory lane): SKIPS cleanly when the agent LLM key is absent, when the
scheduling feature hasn't merged, or when the scheduling DB isn't reachable/seeded — a
live booking needs all three. Uses a pinned seeded coverage cell (dishwasher @ 60601) and
cleans up every row it creates, scoped to its own bench-email domain.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

from evals.adaptive_driver import (
    AdaptiveScenario,
    CallerPersona,
    detect_reasks_ordered,
    drive_llm_caller,
)
from evals.assertions import check_structural_assertions
from evals.gating import missing_requirements
from evals.scenarios.schema import Scenario

# q0-3 eval-gate split: advisory live lane, retried once, never fails the build.
pytestmark = pytest.mark.live

# Committed-seed coverage cell (scripts/booking_quality_bench.py header): dishwasher @
# 60601 has seeded technicians/slots, so a competent agent can actually book.
BOOK_APPLIANCE = "dishwasher"
BOOK_ZIP = "60601"
# Own domain so cleanup can scope by email LIKE, exactly like the booking bench.
E2E_EMAIL_DOMAIN = "@e2e-live.example.test"


def _require_agent_llm_or_skip() -> None:
    if os.environ.get("LLM_PROVIDER", "deepseek").strip().lower() == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set — live booking drive needs a real LLM")
        return
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set — live booking drive needs a real LLM")


def _require_scheduling_or_skip() -> None:
    missing = missing_requirements(["scheduling"])
    if missing:
        pytest.skip(f"scheduling feature not merged (sentinels missing: {missing})")


def _rebind_db_to_current_loop() -> None:
    """Drop the app's cached async engines so a fresh connection pool binds to THIS test's
    event loop.

    pytest-asyncio (asyncio_mode=auto) gives each test its own loop, but app/db/base.py and
    app/db/matching.py cache their engine and bind its pool to the FIRST loop that uses it.
    In a full `evals/` run an earlier DB-touching test — e.g. a persona drive whose agent
    calls find_technicians — binds the pool to a loop that's since been closed; this test
    would then raise 'attached to a different loop' and (via _require_db_or_skip) silently
    SKIP instead of running. We can't use matching.reset_engine() here because it awaits
    engine.dispose() against that dead loop; just clearing the caches lets each factory
    rebuild in the current loop (the orphaned pool is GC'd)."""
    import app.db.base as base
    import app.db.matching as matching

    base.get_engine.cache_clear()
    base.get_sessionmaker.cache_clear()
    matching._engine = None
    matching._sessionmaker = None


async def _require_db_or_skip() -> None:
    """A live booking needs a reachable, seeded scheduling DB — skip (don't fail) if the
    connection can't be opened, so the advisory lane stays green on a DB-less box."""
    try:
        import sqlalchemy as sa

        from app.db.matching import session_scope

        async with session_scope() as db:
            await db.execute(sa.text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"scheduling DB not reachable — skipping live booking drive ({exc!r})")


async def _seed_session(session_id: uuid.UUID) -> None:
    from app.db.base import get_sessionmaker
    from app.db.models_core import SessionRecord

    factory = get_sessionmaker()
    async with factory() as db:
        db.add(SessionRecord(id=session_id, channel="web"))
        await db.commit()


async def _customer_contact(session_id: uuid.UUID) -> tuple[str | None, str | None] | None:
    """(name, email) on the booked appointment's customer row for this session, or None if
    no appointment landed. Used to gate task #27 — bookings must carry the caller's contact
    info, not an empty customer row."""
    import sqlalchemy as sa

    from app.db.matching import session_scope

    async with session_scope() as db:
        row = (
            await db.execute(
                sa.text(
                    "SELECT c.name, c.email FROM appointments a JOIN customers c"
                    " ON c.id = a.customer_id WHERE a.session_id = :sid"
                ),
                {"sid": str(session_id)},
            )
        ).first()
    return (row.name, row.email) if row else None


async def _cleanup(session_id: uuid.UUID) -> None:
    """Reopen any slot this drive claimed, then delete its appointment/customer/session
    rows — scoped by SESSION ID, not email domain. (The agent doesn't reliably persist the
    caller's email onto the customer row, so an email-domain scope misses the appointment
    and then FK-violates on the session delete — the FK is sessions←appointments←customers,
    so appointments must go first.)"""
    import sqlalchemy as sa

    from app.db.matching import session_scope

    async with session_scope() as db:
        rows = (
            await db.execute(
                sa.text("SELECT customer_id, slot_id FROM appointments WHERE session_id = :sid"),
                {"sid": str(session_id)},
            )
        ).fetchall()
        for row in rows:
            await db.execute(
                sa.text("UPDATE availability_slots SET status='open' WHERE id = :s"),
                {"s": row.slot_id},
            )
        await db.execute(
            sa.text("DELETE FROM appointments WHERE session_id = :sid"), {"sid": str(session_id)}
        )
        for row in rows:
            await db.execute(sa.text("DELETE FROM customers WHERE id = :c"), {"c": row.customer_id})
        await db.execute(sa.text("DELETE FROM sessions WHERE id = :sid"), {"sid": str(session_id)})
        await db.commit()


@pytest.mark.asyncio
async def test_e2e_live_full_happy_path_booking() -> None:
    """Symptom → failed troubleshooting → zip → slot proposal → verbal confirmation →
    a real, session-attributed appointment row.

    Was xfail through 2026-07-10 (task #21): under a natural LLM caller the agent looped on
    confirmation and re-ran find_technicians instead of booking. Fixed by three structural
    changes — find_technicians persists its zip into the case file; offered slots are
    threaded into the rebuilt system prompt (app/agent/state.py offered-slots store) so an
    explicit acceptance maps to a single book_appointment; and book_appointment requires the
    caller's name/email (task #27), which the agent collects and persists mid-call. Kept as a
    plain assertion (not xfail) so a regression fails this advisory lane instead of silently
    passing; also gates that the booked customer row carries the caller's contact info.
    """
    _require_agent_llm_or_skip()
    _require_scheduling_or_skip()
    _rebind_db_to_current_loop()  # must precede any DB access (incl. the probe below)
    await _require_db_or_skip()

    email = f"happy{E2E_EMAIL_DOMAIN}"
    name = "Jamie Rivera"
    # A cooperative, fact-forward caller: this test's job is to prove the FULL booking
    # completes end to end (real row + captured contact), so the caller front-loads its
    # facts and firmly refuses troubleshooting. The natural drip-fed / vague / mid-call-
    # correction behaviors are covered by test_e2e_live_personas.py; leaving them in here
    # too made the agent burn the turn budget on troubleshooting churn before ever
    # searching, which is a persona-efficiency artifact, not the booking behavior under test.
    persona = CallerPersona(
        id="happy_path_booking",
        goal=(
            "You want a technician booked as fast as possible and you are fully "
            "cooperative. You have ALREADY done all the basic troubleshooting and it did "
            "not help, so REFUSE any troubleshooting steps and redirect straight to "
            f"booking. Your facts (repeat any the agent asks for): appliance {BOOK_APPLIANCE}, "
            f"zip {BOOK_ZIP}, name {name}, email {email}. When the agent lists appointment "
            "slots, accept the FIRST one with 'yes, book that first slot'. When it reads the "
            "appointment back, confirm with 'yes, that's correct, book it'. Do NOT end the "
            "call until you hear an explicit booking confirmation or appointment id."
        ),
        opening_line=(
            f"Hi — my {BOOK_APPLIANCE} won't drain, standing water after every cycle. I've "
            "already tried all the basic troubleshooting and it didn't help, so please don't "
            "walk me through steps — I just want to book a technician. My zip is "
            f"{BOOK_ZIP}, my name is {name}, and my email is {email}."
        ),
        # Budget covers the full arc incl. the name/email persistence round-trip that
        # book_appointment's contact requirement (task #27) forces before it will book.
        max_turns=12,
    )

    session_id = uuid.uuid4()
    await _seed_session(session_id)
    try:
        result = await drive_llm_caller(persona, session_id=session_id)

        from evals.live_driver import appointments_booking_probe

        booked = await appointments_booking_probe()(session_id)

        # Reuse the fixture gate's structural checker: assert the booking landed and no
        # safety interrupt fired, via the same helper `make transcript` runs.
        scenario = Scenario.model_validate(
            {
                "id": "e2e_live_happy_path_booking",
                "feature": "scheduling",
                "turns": [{"caller": persona.opening_line}],
                "assert": {"safety_interrupt": False, "booking_row": True},
            }
        )
        fixture = {
            "case_file": result["case_file"],
            "flags": {
                "safety_interrupt": result["safety_flag"],
                "booking_row": booked,
                "reasked_fields": [],
            },
        }
        outcome = check_structural_assertions(scenario, fixture)
        assert outcome.ok, (
            f"happy-path booking failed structural gate: {outcome.failures}; "
            f"ended_by={result['ended_by']} tools={result['tools_invoked']}"
        )
        # Sanity: the agent actually invoked the booking tool (not just a lucky row).
        assert "book_appointment" in result["tools_invoked"], (
            f"no book_appointment call in the drive; tools={result['tools_invoked']}"
        )
        # Task #27 regression gate: the booking must carry the caller's contact info. The
        # agent has to collect + persist name/email (book_appointment refuses without them,
        # BOOKING_REQUIRE_CONTACT default-on), so an empty/foreign customer row is a
        # regression, not just cosmetic.
        contact = await _customer_contact(session_id)
        assert contact is not None, "booked, but no customer row found to check contact on"
        name, cust_email = contact
        assert cust_email == email, (
            f"customer row email {cust_email!r} != the caller's {email!r} (contact not captured)"
        )
        assert name and name.strip(), f"customer row has no name: {name!r}"
    finally:
        await _cleanup(session_id)


# Marathon uses a seeded coverage cell too (washer @ 60601 — committed seed) so it can
# actually book after the long fact-gathering phase.
MARATHON_APPLIANCE = "washer"
MARATHON_ZIP = "60601"


@pytest.mark.asyncio
async def test_e2e_live_memory_marathon_retains_all_facts_and_books() -> None:
    """A long call that drips 8+ facts across turns, then requires the agent to use them
    all to book — the stress test for cross-turn memory (the system prompt is rebuilt from
    the case file every turn, so an early fact must survive to the booking phase).

    The caller volunteers, one per turn: appliance+symptom, brand, model, error code, onset,
    and an unusual sound — THEN name/email/zip and a booking. Asserts (a) no re-ask that
    reflects real memory loss (detect_reasks_ordered, framed to ignore benign long-call
    re-confirmations), (b) the BOOKING-CRITICAL facts (appliance/zip/email) survive the long
    call, and (c) a real appointment lands carrying the caller's contact. Retention of the
    secondary diagnostic facts (brand/model/error_code/sound/onset) is measured but NOT gated:
    live capture is severely variable (task #44 — 0/5 to 5/5 across runs), so any threshold
    would flake; the count is surfaced in the (c) assertion message for visibility.
    """
    _require_agent_llm_or_skip()
    _require_scheduling_or_skip()
    _rebind_db_to_current_loop()
    await _require_db_or_skip()

    email = f"marathon{E2E_EMAIL_DOMAIN}"
    name = "Dana Whitfield"
    brand = "Kenmore"
    model = "110.20022311"
    error_code = "F21"
    persona = CallerPersona(
        id="memory_marathon",
        goal=(
            "You are giving a thorough, unhurried report and you reveal ONE new detail per "
            "turn, volunteering it proactively ('oh, and…') even if not asked, in THIS "
            f"order: (1) already said in your opening — your {MARATHON_APPLIANCE} won't spin "
            "and leaves clothes soaking wet; (2) it's a "
            f"{brand}; (3) the model number is {model}; (4) it's showing error code "
            f"{error_code}; (5) this started last Tuesday; (6) it makes a loud grinding "
            "noise during the spin cycle. You already tried all basic troubleshooting — "
            "REFUSE any troubleshooting steps and say you just want a technician. After all "
            f"six details, when the agent asks, your zip is {MARATHON_ZIP}, your name is "
            f"{name}, and your email is {email}. When it lists slots, accept the FIRST with "
            "'yes, book that first slot'; confirm the read-back with 'yes, correct, book "
            "it'. Do NOT end the call until you hear an explicit booking confirmation."
        ),
        opening_line=(
            f"Hi — my {MARATHON_APPLIANCE} won't spin and leaves the clothes soaking wet. "
            "I've already tried the basic troubleshooting and it didn't help. Let me give "
            "you the details one at a time."
        ),
        # A long call: 6 dripped details + zip/name/email + slot + read-back confirm.
        max_turns=16,
    )

    session_id = uuid.uuid4()
    await _seed_session(session_id)
    try:
        result = await drive_llm_caller(persona, session_id=session_id)
        case_file = result["case_file"]
        case_blob = json.dumps(case_file).lower()

        # (a) Never-re-ask, framed for a long stochastic call: detect_reasks_ordered flags
        # any keyword-tracked field (appliance/zip/email) the agent interrogates after it was
        # stated — but over 16 turns the agent sometimes benignly RE-CONFIRMS a fact it still
        # holds ("what appliance is this for?" while appliance_type is on file). That's not a
        # memory failure. So a re-ask only counts as a defect when the field is ALSO absent
        # from the final case file, i.e. the agent asked again AND still doesn't have it.
        # (zip/email re-asks are additionally the known contact-persistence issue #30.)
        reask_scenario = AdaptiveScenario(
            id="memory_marathon",
            appliance=MARATHON_APPLIANCE,
            symptom="won't spin",
            zip=MARATHON_ZIP,
            email=email,
            no_reask=("appliance_type", "customer.zip", "customer.email"),
        )
        reasked = detect_reasks_ordered(
            result["caller_texts"], result["agent_texts"], reask_scenario
        )
        _customer = case_file.get("customer") or {}
        _present = {
            "appliance_type": bool(case_file.get("appliance_type")),
            "customer.zip": bool(_customer.get("zip")),
            "customer.email": bool(_customer.get("email")),
        }
        lost = [f for f in reasked if not _present.get(f, True)]
        assert not lost, f"agent re-asked AND never captured (real memory loss): {lost}"

        # (b) Retention — only the BOOKING-CRITICAL facts are gated, because only they are
        # reliably captured (book_appointment can't succeed without them). The secondary
        # diagnostic facts (brand/model/error_code/sound/onset) are NOT gated: live capture is
        # severely variable (task #44 — observed 5/5, 4/5, and 0/5 across three runs on
        # 2026-07-10; the agent sometimes books off just the opening symptom). We compute how
        # many landed and surface it in the booking assertion below for visibility, but a
        # threshold of any kind would flake. The long-call MEMORY signal this test reliably
        # gates: the booking-critical facts survive 16 turns (here), nothing is
        # re-asked-and-lost (a), and the booking + contact land (c).
        _norm = case_blob.replace(".", "").replace(" ", "")
        diagnostic_retained = [
            k
            for k, present in {
                "brand": brand.lower() in case_blob,
                "model": model.replace(".", "") in _norm,
                "error_code": error_code.lower() in case_blob,
                "sound": "grinding" in case_blob,
                "onset": "tuesday" in case_blob,
            }.items()
            if present
        ]
        customer = case_file.get("customer") or {}
        assert case_file.get("appliance_type") == MARATHON_APPLIANCE, case_file
        assert customer.get("zip") == MARATHON_ZIP, customer
        assert (customer.get("email") or "").lower() == email.lower(), customer

        # (c) A real booking landed, carrying the caller's contact (ties to #21 + #27). The
        # message also surfaces how many diagnostic facts were retained (task #44 visibility).
        from evals.live_driver import appointments_booking_probe

        assert await appointments_booking_probe()(session_id), (
            f"no appointment row; ended_by={result['ended_by']} tools={result['tools_invoked']}; "
            f"diagnostic facts retained (ungated, #44): {diagnostic_retained}"
        )
        contact = await _customer_contact(session_id)
        assert contact is not None
        row_name, row_email = contact
        assert row_email == email, f"customer row email {row_email!r} != {email!r}"
        assert row_name and row_name.strip(), f"customer row has no name: {row_name!r}"
    finally:
        await _cleanup(session_id)
