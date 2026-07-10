"""Anti-drift guards: the canonical prose (`specs/latency/budgets.md`), the machine
source of truth (`app/latency/budgets.py`), and every code consumer must agree.

These tests are what makes "budgets live in ONE place" enforceable rather than
aspirational — a number edited in only one location fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.latency import budgets

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPEC_PATH = REPO_ROOT / "specs" / "latency" / "budgets.md"
TECH_DESIGN_PATH = REPO_ROOT / "docs" / "technical-design.md"
CONTRACT_SPEC_PATH = (
    REPO_ROOT / "specs" / "features" / "2026-07-08-latency-engineering" / "requirements.md"
)


def _parse_spec_table() -> dict[str, float]:
    text = SPEC_PATH.read_text()
    match = re.search(r"<!-- budgets:begin -->\n(.*?)<!-- budgets:end -->", text, re.DOTALL)
    assert match, "budgets:begin/end markers missing from specs/latency/budgets.md"
    rows: dict[str, float] = {}
    for line in match.group(1).splitlines():
        m = re.match(r"\|\s*([a-z0-9_]+)\s*\|\s*([0-9.]+)\s*\|", line)
        if m:
            rows[m.group(1)] = float(m.group(2))
    return rows


def test_spec_table_matches_module():
    spec = _parse_spec_table()
    assert spec == budgets.ALL_BUDGETS_MS, (
        "specs/latency/budgets.md and app/latency/budgets.py disagree — "
        "edit them together (see the spec's 'To change a budget' procedure)"
    )


def test_bench_uses_central_budgets():
    from scripts import latency_bench

    assert latency_bench.MICRO_BUDGETS_MS is budgets.MICRO_BUDGETS_MS
    assert latency_bench.PHONE_E2E is budgets.PHONE_E2E
    assert latency_bench.WEB_E2E is budgets.WEB_E2E
    # The old module-local e2e literals must not resurface.
    assert not hasattr(latency_bench, "E2E_P50_BUDGET_MS")
    assert not hasattr(latency_bench, "E2E_P95_BUDGET_MS")


def test_phone_latency_module_uses_central_budgets():
    from app.phone import latency

    assert latency.P50_BUDGET_S == budgets.PHONE_E2E.p50_s
    assert latency.P95_BUDGET_S == budgets.PHONE_E2E.p95_s


def test_technical_design_summary_matches():
    """The reviewer-facing summary rows in docs/technical-design.md are pinned to the
    module — the doc says 'canonical: specs/latency/budgets.md' and these rows prove it."""
    text = TECH_DESIGN_PATH.read_text()
    assert "specs/latency/budgets.md" in text

    web = re.search(
        r"Web: first perceived audio \(cached filler\) \| p50 < ([\d.]+) s, p95 < ([\d.]+) s",
        text,
    )
    assert web, "web perceived budget summary row missing from technical-design.md"
    assert float(web.group(1)) == budgets.WEB_E2E.p50_s
    assert float(web.group(2)) == budgets.WEB_E2E.p95_s

    web_meaningful = re.search(
        r"Web: first meaningful reply audio \| p50 < ([\d.]+) s, p95 < ([\d.]+) s", text
    )
    assert web_meaningful, "web meaningful budget summary row missing from technical-design.md"
    assert float(web_meaningful.group(1)) == budgets.WEB_MEANINGFUL.p50_s
    assert float(web_meaningful.group(2)) == budgets.WEB_MEANINGFUL.p95_s

    phone = re.search(
        r"Phone: end-of-caller-speech → first perceived audio \| "
        r"p50 ≤ ([\d.]+) s, p95 ≤ ([\d.]+) s",
        text,
    )
    assert phone, "phone perceived budget summary row missing from technical-design.md"
    assert float(phone.group(1)) == budgets.PHONE_E2E.p50_s
    assert float(phone.group(2)) == budgets.PHONE_E2E.p95_s

    phone_meaningful = re.search(
        r"Phone: first meaningful reply audio \| p50 ≤ ([\d.]+) s, p95 ≤ ([\d.]+) s", text
    )
    assert phone_meaningful, "phone meaningful budget summary row missing"
    assert float(phone_meaningful.group(1)) == budgets.PHONE_MEANINGFUL.p50_s
    assert float(phone_meaningful.group(2)) == budgets.PHONE_MEANINGFUL.p95_s

    web_token = re.search(r"Web: first text token \| < ([\d.]+) s", text)
    assert web_token, "web first-token summary row missing from technical-design.md"
    assert float(web_token.group(1)) * 1000 == budgets.WEB_FIRST_TOKEN.budget_ms


def test_spec_contract_table_names_exist():
    """Every test the latency-engineering 'Regression-proof test contract' table names
    must exist in tests/latency/ — kills contract-vs-reality drift permanently."""
    text = CONTRACT_SPEC_PATH.read_text()
    named = set(re.findall(r"`(test_[a-z0-9_]+)`", text))
    assert named, "no test names found in the contract spec — did the table move?"

    latency_tests_dir = Path(__file__).resolve().parent
    defined = set()
    for path in latency_tests_dir.glob("test_*.py"):
        defined.update(re.findall(r"^(?:async )?def (test_[a-z0-9_]+)\(", path.read_text(), re.M))

    missing = named - defined
    assert not missing, (
        f"contract table names tests that don't exist in tests/latency/: {sorted(missing)} — "
        "update the spec table or implement the test"
    )
