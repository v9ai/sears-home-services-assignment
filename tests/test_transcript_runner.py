"""`make transcript` gate: runs the full scenario matrix in fixture mode."""

from __future__ import annotations

from scripts.transcript_runner import run


def test_transcript_runner_matrix_passes_and_canaries_fail_as_expected(capsys):
    exit_code = run()
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out
    assert "transcript gate: PASS" in captured.out


def test_transcript_runner_skips_requires_gated_scenarios_visibly(capsys):
    run()
    captured = capsys.readouterr()
    assert "SKIP" in captured.out
    assert "requires unmet: scheduling" in captured.out
    assert "requires unmet: visual" in captured.out
