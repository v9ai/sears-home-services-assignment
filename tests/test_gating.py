"""`requires:` feature-availability gating (COORDINATION.md §4)."""

from __future__ import annotations

from evals import gating


def test_missing_requirements_detects_absent_sentinels(tmp_path):
    assert gating.missing_requirements(["scheduling"], root=tmp_path) == ["scheduling"]
    assert gating.missing_requirements(["visual"], root=tmp_path) == ["visual"]


def test_missing_requirements_clears_once_sentinels_exist(tmp_path):
    (tmp_path / "app" / "tools").mkdir(parents=True)
    (tmp_path / "app" / "db").mkdir(parents=True)
    (tmp_path / "app" / "tools" / "scheduling_tools.py").write_text("")
    (tmp_path / "app" / "db" / "models_scheduling.py").write_text("")
    assert gating.missing_requirements(["scheduling"], root=tmp_path) == []


def test_partial_sentinels_still_count_as_missing(tmp_path):
    (tmp_path / "app" / "tools").mkdir(parents=True)
    (tmp_path / "app" / "tools" / "scheduling_tools.py").write_text("")
    # models_scheduling.py absent -> feature not fully merged yet.
    assert gating.missing_requirements(["scheduling"], root=tmp_path) == ["scheduling"]


def test_unknown_requirement_name_is_never_gated(tmp_path):
    assert gating.missing_requirements(["not_a_real_feature"], root=tmp_path) == []


def test_empty_requirements_list_is_always_satisfied(tmp_path):
    assert gating.missing_requirements([], root=tmp_path) == []


def test_repo_state_today_activates_scheduling_and_visual():
    # Post-integration (COORDINATION.md §5): scheduling and visual are merged, so their
    # sentinel files are present in this worktree and their scenarios are no longer gated.
    assert gating.missing_requirements(["scheduling"]) == []
    assert gating.missing_requirements(["visual"]) == []
