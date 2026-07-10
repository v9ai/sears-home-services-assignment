"""latency_compare must display the budget its pass flag was gated on (B6).

Post-h1, the e2e `pass` flag is computed against the MEANINGFUL budget
(phone 3200/web 2800) and the summary records it as ``budget_p50_ms`` — but
``compare()`` looked the display budget up in ``budgets_ms`` under the
perceived keys (phone 2500/web 2200), so the table printed one budget while
the transition column reflected a gate against another.
"""

from __future__ import annotations

from scripts.latency_compare import compare


def _minimal_report(*, phone_gate_budget: float | None, web_gate_budget: float | None) -> dict:
    def e2e(field: str, p50: float, gate: float | None) -> dict:
        summary = {f"p50_{field}": p50, "pass": True}
        if gate is not None:
            summary["budget_p50_ms"] = gate
        return summary

    return {
        "schema_version": 2,
        "micro_benchmarks": {},
        "end_to_end": {
            "web": e2e("submit_to_first_audio_ms", 1800.0, web_gate_budget),
            "phone": e2e("eos_to_first_audio_ms", 2900.0, phone_gate_budget),
        },
        # Perceived-era keys — deliberately different from the gate budgets.
        "budgets_ms": {"phone_e2e_p50_ms": 2500, "web_e2e_p50_ms": 2200},
    }


def test_displayed_budget_matches_the_gated_budget() -> None:
    report = _minimal_report(phone_gate_budget=3200, web_gate_budget=2800)
    stages = compare(report, report)
    assert stages["phone_e2e_p50_ms"]["budget"] == 3200, (
        "phone row must show the meaningful budget its pass flag used, not the "
        "perceived 2500 from budgets_ms"
    )
    assert stages["web_e2e_p50_ms"]["budget"] == 2800


def test_legacy_report_without_gate_budget_falls_back_to_budgets_ms() -> None:
    report = _minimal_report(phone_gate_budget=None, web_gate_budget=None)
    stages = compare(report, report)
    assert stages["phone_e2e_p50_ms"]["budget"] == 2500
    assert stages["web_e2e_p50_ms"]["budget"] == 2200
