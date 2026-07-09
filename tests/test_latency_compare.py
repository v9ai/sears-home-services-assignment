"""Offline tests for `scripts/latency_compare.py` — fabricated schema-v2 reports only
(the same shape `scripts/latency_bench.py::build_report` writes); no network, no
`data/latency/` dependency.
"""

from __future__ import annotations

import json

import pytest

from scripts import latency_compare


def _report(
    *,
    timestamp: str,
    llm_ttft_p50: float,
    llm_ttft_pass: bool,
    phone_p50: float,
    phone_pass: bool,
    overall: bool,
) -> dict:
    return {
        "schema_version": 2,
        "timestamp": timestamp,
        "llm_provider": "openai",
        "micro_benchmarks": {
            "eos_to_stt_ms": {
                "samples_ms": [500.0],
                "p50": 500.0,
                "p95": 500.0,
                "budget_ms": 900,
                "pass": True,
            },
            "llm_ttft_ms": {
                "samples_ms": [llm_ttft_p50],
                "p50": llm_ttft_p50,
                "p95": llm_ttft_p50,
                "budget_ms": 1200,
                "pass": llm_ttft_pass,
            },
            "tts_first_byte_ms": {
                "samples_ms": [300.0],
                "p50": 300.0,
                "p95": 300.0,
                "budget_ms": 500,
                "pass": True,
            },
        },
        "end_to_end": {
            "web": {
                "records": [],
                "p50_submit_to_first_audio_ms": 1800.0,
                "p95_submit_to_first_audio_ms": 1900.0,
                "budget_p50_ms": 2000,
                "budget_p95_ms": 3500,
                "pass": True,
            },
            "phone": {
                "records": [],
                "p50_eos_to_first_audio_ms": phone_p50,
                "p95_eos_to_first_audio_ms": phone_p50,
                "budget_p50_ms": 2500,
                "budget_p95_ms": 4000,
                "pass": phone_pass,
                "note": "pre-L7",
            },
        },
        "budgets_ms": {
            "eos_to_stt_ms": 900,
            "llm_ttft_ms": 1200,
            "tts_first_byte_ms": 500,
            "web_e2e_p50_ms": 2000,
            "web_e2e_p95_ms": 3500,
            "phone_e2e_p50_ms": 2500,
            "phone_e2e_p95_ms": 4000,
        },
        "overall_pass": overall,
    }


BEFORE = _report(
    timestamp="20260709T100000Z",
    llm_ttft_p50=1450.0,
    llm_ttft_pass=False,
    phone_p50=4200.0,
    phone_pass=False,
    overall=False,
)
AFTER = _report(
    timestamp="20260709T110000Z",
    llm_ttft_p50=610.0,
    llm_ttft_pass=True,
    phone_p50=2300.0,
    phone_pass=True,
    overall=True,
)


def test_compare_delta_math():
    stages = latency_compare.compare(BEFORE, AFTER)

    llm = stages["llm_ttft_ms"]
    assert llm["before_p50"] == 1450.0
    assert llm["after_p50"] == 610.0
    assert llm["budget"] == 1200
    assert llm["delta_pct"] == pytest.approx(-57.9, abs=0.1)

    phone = stages["phone_e2e_p50_ms"]
    assert phone["before_p50"] == 4200.0
    assert phone["after_p50"] == 2300.0
    assert phone["budget"] == 2500
    assert phone["delta_pct"] == pytest.approx(-45.2, abs=0.1)

    # unchanged stage: zero delta
    assert stages["eos_to_stt_ms"]["delta_pct"] == 0.0


def test_compare_flags_transitions():
    stages = latency_compare.compare(BEFORE, AFTER)
    assert stages["llm_ttft_ms"]["before_pass"] is False
    assert stages["llm_ttft_ms"]["after_pass"] is True  # FAIL->PASS
    assert stages["eos_to_stt_ms"]["before_pass"] is True
    assert stages["eos_to_stt_ms"]["after_pass"] is True


def test_render_table_marks_regression():
    # Reverse direction: a PASS->FAIL crossing must be loudly flagged.
    table = latency_compare.render_table(latency_compare.compare(AFTER, BEFORE), AFTER, BEFORE)
    assert "PASS->FAIL  <-- REGRESSION" in table
    assert "overall_pass: True -> False" in table


def test_render_table_marks_fail_to_pass():
    table = latency_compare.render_table(latency_compare.compare(BEFORE, AFTER), BEFORE, AFTER)
    assert "FAIL->PASS" in table
    assert "REGRESSION" not in table


def test_summary_json_shape(tmp_path, capsys):
    before_path = tmp_path / "a.json"
    after_path = tmp_path / "b.json"
    before_path.write_text(json.dumps(BEFORE))
    after_path.write_text(json.dumps(AFTER))

    rc = latency_compare.main([str(before_path), str(after_path), "--summary-json"])

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    # Exactly the ledger `stages` object: no pass flags, all four value keys present.
    assert set(summary["llm_ttft_ms"]) == {"before_p50", "after_p50", "budget", "delta_pct"}
    assert "web_e2e_p50_ms" in summary
    assert "phone_e2e_p50_ms" in summary


def test_latest_reports_picks_newest_two_oldest_first(tmp_path):
    for ts in ("20260709T090000Z", "20260709T100000Z", "20260709T110000Z"):
        (tmp_path / f"{ts}.json").write_text(
            json.dumps(
                _report(
                    timestamp=ts,
                    llm_ttft_p50=1.0,
                    llm_ttft_pass=True,
                    phone_p50=1.0,
                    phone_pass=True,
                    overall=True,
                )
            )
        )

    paths = latency_compare.latest_reports(2, reports_dir=tmp_path)

    assert [p.name for p in paths] == ["20260709T100000Z.json", "20260709T110000Z.json"]


def test_latest_reports_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="make latency"):
        latency_compare.latest_reports(2, reports_dir=tmp_path / "nope")


def test_wrong_schema_version_rejected(tmp_path):
    bad = dict(BEFORE, schema_version=1)
    path = tmp_path / "old.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="schema_version 2"):
        latency_compare.load_report(path)


def test_main_exit_2_on_missing_reports(tmp_path, capsys):
    rc = latency_compare.main([str(tmp_path / "x.json"), str(tmp_path / "y.json")])
    assert rc == 2
    assert "ERROR" in capsys.readouterr().err
