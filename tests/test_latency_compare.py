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


# --- paired mode (loop v2 q0-1) --------------------------------------------------------


def _rec_web(scenario: str, turn: int, e2e: float, first_token: float | None = None) -> dict:
    return {
        "channel": "web",
        "scenario_id": scenario,
        "turn_index": turn,
        "submit_to_first_audio_ms": e2e,
        "submit_to_first_token_ms": first_token,
    }


def _rec_phone(scenario: str, turn: int, e2e: float) -> dict:
    return {
        "channel": "phone",
        "scenario_id": scenario,
        "turn_index": turn,
        "eos_to_first_audio_ms": e2e,
    }


def _paired_reports(before_web, after_web, before_phone=(), after_phone=()):
    def wrap(web_records, phone_records, ts):
        r = json.loads(json.dumps(BEFORE))  # deep copy of a valid schema-v2 report
        r["timestamp"] = ts
        r["end_to_end"]["web"]["records"] = list(web_records)
        r["end_to_end"]["phone"]["records"] = list(phone_records)
        return r

    return (
        wrap(before_web, before_phone, "20260710T090000Z"),
        wrap(after_web, after_phone, "20260710T100000Z"),
    )


def test_paired_median_delta_and_sign_counts():
    before, after = _paired_reports(
        before_web=[
            _rec_web("s1", 0, 2000.0),
            _rec_web("s1", 1, 3000.0),
            _rec_web("s2", 0, 1000.0),
        ],
        after_web=[_rec_web("s1", 0, 1800.0), _rec_web("s1", 1, 3300.0), _rec_web("s2", 0, 800.0)],
    )

    paired = latency_compare.compare_paired(before, after)

    web = paired["web"]
    # deltas: -10%, +10%, -20% -> median -10%, 2 improving, 1 regressing
    assert web["n_pairs"] == 3
    assert web["median_delta_pct"] == pytest.approx(-10.0)
    assert web["improving"] == 2
    assert web["regressing"] == 1


def test_paired_matches_on_scenario_and_turn_not_order():
    # Same records, shuffled order in the after report: every pair must be 0% delta.
    before, after = _paired_reports(
        before_web=[_rec_web("s1", 0, 2000.0), _rec_web("s2", 0, 1000.0)],
        after_web=[_rec_web("s2", 0, 1000.0), _rec_web("s1", 0, 2000.0)],
    )

    paired = latency_compare.compare_paired(before, after)

    assert paired["web"]["n_pairs"] == 2
    assert paired["web"]["median_delta_pct"] == 0.0


def test_paired_skips_unmatched_and_none_values():
    before, after = _paired_reports(
        before_web=[
            _rec_web("s1", 0, 2000.0),
            _rec_web("only-before", 0, 999.0),
            _rec_web("s3", 0, None),
        ],
        after_web=[
            _rec_web("s1", 0, 1000.0),
            _rec_web("only-after", 0, 111.0),
            _rec_web("s3", 0, 500.0),
        ],
    )

    paired = latency_compare.compare_paired(before, after)

    web = paired["web"]
    assert web["n_pairs"] == 1  # only s1/0 qualifies
    assert web["unmatched_before"] == 1
    assert web["unmatched_after"] == 1


def test_paired_segments_reported_when_present():
    before, after = _paired_reports(
        before_web=[_rec_web("s1", 0, 2000.0, first_token=1000.0)],
        after_web=[_rec_web("s1", 0, 1500.0, first_token=600.0)],
    )

    paired = latency_compare.compare_paired(before, after)

    seg = paired["web"]["segments"]["submit_to_first_token_ms"]
    assert seg["n_pairs"] == 1
    assert seg["median_delta_pct"] == pytest.approx(-40.0)


def test_paired_phone_channel_uses_eos_metric():
    before, after = _paired_reports(
        before_web=[],
        after_web=[],
        before_phone=[_rec_phone("p1", 0, 3000.0)],
        after_phone=[_rec_phone("p1", 0, 2400.0)],
    )

    paired = latency_compare.compare_paired(before, after)

    assert paired["phone"]["metric"] == "eos_to_first_audio_ms"
    assert paired["phone"]["median_delta_pct"] == pytest.approx(-20.0)
    assert paired["web"]["n_pairs"] == 0  # empty channel degrades gracefully


def test_paired_cli_summary_json(tmp_path, capsys):
    before, after = _paired_reports(
        before_web=[_rec_web("s1", 0, 2000.0)],
        after_web=[_rec_web("s1", 0, 1500.0)],
    )
    bp, ap = tmp_path / "b.json", tmp_path / "a.json"
    bp.write_text(json.dumps(before))
    ap.write_text(json.dumps(after))

    rc = latency_compare.main([str(bp), str(ap), "--paired", "--summary-json"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["web"]["median_delta_pct"] == pytest.approx(-25.0)


def test_paired_cli_table_renders(tmp_path, capsys):
    before, after = _paired_reports(
        before_web=[_rec_web("s1", 0, 2000.0)],
        after_web=[_rec_web("s1", 0, 1500.0)],
    )
    bp, ap = tmp_path / "b.json", tmp_path / "a.json"
    bp.write_text(json.dumps(before))
    ap.write_text(json.dumps(after))

    rc = latency_compare.main([str(bp), str(ap), "--paired"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "paired compare" in out
    assert "web/submit_to_first_audio_ms" in out


# --- coverage: compare() skip branches, delta guard, CLI wiring -------------------------


def test_compare_skips_micro_stage_absent_in_after():
    # A stage that vanished from the after report has no pair -> it must be dropped, not
    # compared against a phantom.
    after = json.loads(json.dumps(AFTER))
    del after["micro_benchmarks"]["tts_first_byte_ms"]

    stages = latency_compare.compare(BEFORE, after)

    assert "tts_first_byte_ms" not in stages
    assert "llm_ttft_ms" in stages  # surviving stages still compare


def test_compare_skips_e2e_channel_missing_p50():
    after = json.loads(json.dumps(AFTER))
    after["end_to_end"]["phone"]["p50_eos_to_first_audio_ms"] = None

    stages = latency_compare.compare(BEFORE, after)

    assert "phone_e2e_p50_ms" not in stages  # no usable pair -> skipped, never a crash
    assert "web_e2e_p50_ms" in stages


def test_compare_delta_is_none_when_before_is_zero():
    # A zero baseline can't produce a percentage delta -- guarded to None (renders n/a),
    # never a ZeroDivisionError.
    before = json.loads(json.dumps(BEFORE))
    before["micro_benchmarks"]["llm_ttft_ms"]["p50"] = 0.0

    stages = latency_compare.compare(before, AFTER)

    assert stages["llm_ttft_ms"]["delta_pct"] is None


def test_render_table_marks_fail_unchanged():
    # Both runs fail the same stage (no transition) -> "FAIL (unchanged)", not a
    # regression flag.
    worse = _report(
        timestamp="20260709T120000Z",
        llm_ttft_p50=1500.0,
        llm_ttft_pass=False,
        phone_p50=4300.0,
        phone_pass=False,
        overall=False,
    )

    table = latency_compare.render_table(latency_compare.compare(BEFORE, worse), BEFORE, worse)

    assert "FAIL (unchanged)" in table
    assert "REGRESSION" not in table


def test_main_latest_only_supports_two(capsys):
    with pytest.raises(SystemExit) as exc:
        latency_compare.main(["--latest", "3"])
    assert exc.value.code == 2
    assert "only supports 2" in capsys.readouterr().err


def test_main_requires_exactly_two_report_paths(capsys):
    with pytest.raises(SystemExit) as exc:
        latency_compare.main(["only-one.json"])
    assert exc.value.code == 2


def test_main_latest_two_reads_newest_pair(monkeypatch, tmp_path, capsys):
    bp, ap = tmp_path / "b.json", tmp_path / "a.json"
    bp.write_text(json.dumps(BEFORE))
    ap.write_text(json.dumps(AFTER))
    monkeypatch.setattr(latency_compare, "latest_reports", lambda n: [bp, ap])

    rc = latency_compare.main(["--latest", "2"])

    assert rc == 0
    assert "latency compare" in capsys.readouterr().out


def test_paired_phone_segments_reported():
    # The phone channel's per-stage segments (eos->stt, stt->first-token) pair the same
    # way the e2e metric does.
    before = json.loads(json.dumps(BEFORE))
    after = json.loads(json.dumps(AFTER))
    before["end_to_end"]["phone"]["records"] = [
        {
            "scenario_id": "p1",
            "turn_index": 0,
            "eos_to_first_audio_ms": 3000.0,
            "eos_to_stt_ms": 800.0,
            "stt_to_agent_first_token_ms": 1200.0,
        }
    ]
    after["end_to_end"]["phone"]["records"] = [
        {
            "scenario_id": "p1",
            "turn_index": 0,
            "eos_to_first_audio_ms": 2400.0,
            "eos_to_stt_ms": 600.0,
            "stt_to_agent_first_token_ms": 900.0,
        }
    ]

    paired = latency_compare.compare_paired(before, after)

    segs = paired["phone"]["segments"]
    assert segs["eos_to_stt_ms"]["median_delta_pct"] == pytest.approx(-25.0)
    assert segs["stt_to_agent_first_token_ms"]["median_delta_pct"] == pytest.approx(-25.0)


def test_render_paired_table_reports_no_matched_pairs():
    before = json.loads(json.dumps(BEFORE))
    after = json.loads(json.dumps(AFTER))
    # Disjoint scenarios on each side -> zero matched pairs.
    before["end_to_end"]["web"]["records"] = [_rec_web("only-before", 0, 2000.0)]
    after["end_to_end"]["web"]["records"] = [_rec_web("only-after", 0, 1500.0)]

    paired = latency_compare.compare_paired(before, after)
    table = latency_compare.render_paired_table(paired, before, after)

    assert paired["web"]["n_pairs"] == 0
    assert "no matched pairs" in table
