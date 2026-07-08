"""`make transcript` gate: runs the full scenario matrix in fixture mode."""

from __future__ import annotations

from scripts.transcript_runner import run


def test_transcript_runner_matrix_passes_and_canaries_fail_as_expected(capsys):
    exit_code = run()
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out
    assert "transcript gate: PASS" in captured.out


def test_transcript_runner_activates_previously_gated_scenarios(capsys):
    # Post-integration (COORDINATION.md §5): scheduling + visual are merged, so their
    # `requires:`-gated scenarios run instead of skipping.
    run()
    captured = capsys.readouterr()
    assert "requires unmet" not in captured.out
    assert "PASS  scheduling_happy_booking" in captured.out
    assert "PASS  visual_email_spellback" in captured.out
