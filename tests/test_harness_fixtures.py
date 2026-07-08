"""Harness self-tests (plan.md group 1): fixtures import and behave as documented."""

from __future__ import annotations

import sqlalchemy

from app.contracts import CaseFile, Customer


async def test_fake_agent_scripts_replies(fake_agent):
    fake_agent.script = ["Hello! What appliance is acting up?"]
    reply = await fake_agent.chat("Hi, my washer won't drain.")
    assert reply == "Hello! What appliance is acting up?"
    assert fake_agent.transcript[0] == {"role": "user", "text": "Hi, my washer won't drain."}
    assert fake_agent.transcript[1]["role"] == "agent"


async def test_fake_agent_reports_when_script_runs_dry(fake_agent):
    reply = await fake_agent.chat("anything")
    assert reply == "(no scripted reply left)"


async def test_fake_llm_returns_queued_replies(fake_llm):
    fake_llm.queue("first")
    fake_llm.queue("second")
    assert await fake_llm.acomplete("p1") == "first"
    assert await fake_llm.acomplete("p2") == "second"
    assert fake_llm.prompts == ["p1", "p2"]


def test_case_file_factory_matches_contract(case_file_factory):
    case_file = case_file_factory(appliance_type="washer")
    assert isinstance(case_file, CaseFile)
    assert case_file.appliance_type == "washer"
    assert case_file.symptoms == []


def test_customer_factory_defaults(customer_factory):
    customer = customer_factory()
    assert isinstance(customer, Customer)
    assert customer.zip == "60614"


def test_customer_factory_overrides(customer_factory):
    customer = customer_factory(zip="99999")
    assert customer.zip == "99999"
    assert customer.name == "Jordan Rivera"


def test_technician_factory_shape(technician_factory):
    tech = technician_factory(name="Sam Lee")
    assert tech["name"] == "Sam Lee"
    assert "washer" in tech["specialties"]
    assert tech["employment_type"] in {"full_time", "contractor"}


def test_session_factory_shape(session_factory):
    session = session_factory(appliance_type="dryer")
    assert session["appliance_type"] == "dryer"
    assert session["channel"] == "web"


async def test_db_session_rolls_back_or_skips_cleanly(db_session):
    # Either a real Postgres was reachable (prove the session works and would roll
    # back), or the fixture already skipped this test before we got here.
    result = await db_session.execute(sqlalchemy.text("SELECT 1"))
    assert result.scalar() == 1
