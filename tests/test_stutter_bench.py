"""Stutter-bench tests (stutter-iterate q1) — pin the schema and run the probes
in-process so `make test` alone catches bench rot.

The bench (`scripts/stutter_bench.py`) is the phone-audio-quality loop's metric: four
hermetic probes encoding the 2026-07-09 barge-in echo-loop RCA. These tests assert the
probe verdicts against the CURRENT production guard, so a regression in
`_build_user_turn_strategies` (or the bench itself) fails the suite, not just the
soft-gated bench run.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pipecat.turns.user_start.min_words_user_turn_start_strategy")

from scripts import stutter_bench  # noqa: E402

REQUIRED_PROBE_KEYS = {"budget", "pass"}


@pytest.fixture(autouse=True)
def _production_default_knobs(monkeypatch):
    """The bench measures production defaults; shells must not skew the probes."""
    monkeypatch.delenv("VOICE_BARGEIN_MIN_WORDS", raising=False)
    monkeypatch.delenv("VOICE_BARGEIN_TAIL_MS", raising=False)


# --- probes against the current production guard ---------------------------------


async def test_echo_storm_probe_passes_with_production_guard():
    probe = await stutter_bench.probe_echo_storm()
    assert probe["echo_events_injected"] == 6
    assert probe["echo_turns_opened"] == 0  # the RCA scenario must stay dead
    assert probe["genuine_bargein_honored"] is True  # anti-overcorrection invariant
    assert probe["pass"] is True


async def test_clear_accounting_probe_counts_exactly():
    probe = await stutter_bench.probe_clear_accounting(genuine_interruptions=2)
    assert probe["clears_sent"] == 2
    assert probe["genuine_interruptions"] == 2
    assert probe["pass"] is True


async def test_phantom_tail_probe_enforced_by_echo_tail_guard():
    """f1 (EchoTailMinWordsStrategy) closed the measured gap: a trailing 1-word echo
    inside the tail window opens NO turn, and — the anti-overcorrection half — a
    quick one-word real answer after the window still opens one. Enforced: a
    regression here fails the bench, not just this test."""
    probe = await stutter_bench.probe_phantom_tail()
    assert probe["enforced"] is stutter_bench.PHANTOM_TAIL_ENFORCED is True
    assert probe["tail_echo_turns_opened"] == 0  # was 1 before f1 (ledger i1)
    assert probe["post_window_turn_opened"] is True
    assert probe["pass"] is True


async def test_pacing_probe_smoke(monkeypatch):
    """Short run (0.6 s x 3) — pins the probe mechanics and the 20 ms Twilio-idiomatic
    production cadence (VOICE_OUT_10MS_CHUNKS default 2, stutter-loop f2), not the
    timing budgets themselves."""
    monkeypatch.delenv("VOICE_OUT_10MS_CHUNKS", raising=False)
    monkeypatch.setattr(stutter_bench, "PACING_SECONDS", 0.6)
    monkeypatch.setattr(stutter_bench, "PACING_MIN_SENDS", 8)
    probe = await stutter_bench.probe_pacing()
    assert probe["cadence_ms"] == 20.0
    assert probe["budget"]["cadence_ms"] == 20
    assert probe["runs"] == stutter_bench.PACING_RUNS == 3
    assert probe["sends_min"] >= 8
    assert probe["max_gap_ms_median"] > 0
    assert {"noise_pct", "frame_interval_p95_ms", "gaps_over_2x_cadence_median"} <= set(probe)


# --- report assembly + wiring -----------------------------------------------------


def test_build_report_schema_and_overall_pass_logic():
    probes = {
        "echo_storm": {"budget": {}, "pass": True},
        "pacing": {"budget": {}, "pass": True},
    }
    report = stutter_bench.build_report(probes)
    assert report["schema_version"] == 1
    assert report["timestamp_utc"].endswith("Z")
    assert report["overall_pass"] is True
    for probe in report["probes"].values():
        assert REQUIRED_PROBE_KEYS <= set(probe)

    probes["pacing"]["pass"] = False
    assert stutter_bench.build_report(probes)["overall_pass"] is False


def _canned_failing_report():
    return stutter_bench.build_report(
        {
            "echo_storm": {"budget": {}, "pass": False},
            "clear_accounting": {"budget": {}, "pass": True},
            "phantom_tail": {"budget": {}, "pass": True, "enforced": True},
            "pacing": {"budget": {}, "pass": True},
        }
    )


def test_hard_gate_exits_nonzero_on_fail(monkeypatch, tmp_path):
    """Gate-flip (2026-07-10): a failing report must fail the build."""

    async def _canned_bench():
        return _canned_failing_report()

    monkeypatch.setattr(stutter_bench, "run_bench", _canned_bench)
    monkeypatch.setattr(stutter_bench, "OUT_DIR", tmp_path)
    monkeypatch.delenv("STUTTER_GATE_HARD", raising=False)  # default is hard

    with pytest.raises(SystemExit) as excinfo:
        stutter_bench.main()
    assert excinfo.value.code == 1


def test_gate_escape_hatch_reports_only(monkeypatch, tmp_path, capsys):
    """STUTTER_GATE_HARD=0: report-only mode still writes + prints, never exits."""

    async def _canned_bench():
        return _canned_failing_report()

    monkeypatch.setattr(stutter_bench, "run_bench", _canned_bench)
    monkeypatch.setattr(stutter_bench, "OUT_DIR", tmp_path)
    monkeypatch.setenv("STUTTER_GATE_HARD", "0")

    stutter_bench.main()  # no SystemExit

    assert "stutter-bench overall: FAIL" in capsys.readouterr().out
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_main_writes_report_and_prints_verdicts(monkeypatch, tmp_path, capsys):
    canned = stutter_bench.build_report(
        {
            "echo_storm": {"budget": {}, "pass": True},
            "clear_accounting": {"budget": {}, "pass": True},
            "phantom_tail": {"budget": {}, "pass": True, "enforced": False},
            "pacing": {"budget": {}, "pass": True},
        }
    )

    async def _canned_bench():
        return canned

    monkeypatch.setattr(stutter_bench, "run_bench", _canned_bench)
    monkeypatch.setattr(stutter_bench, "OUT_DIR", tmp_path)

    stutter_bench.main()

    written = list(tmp_path.glob("*.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_text()) == canned
    out = capsys.readouterr().out
    assert "stutter-bench overall: PASS" in out
    assert "phantom_tail: PASS (advisory)" in out
