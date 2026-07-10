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


def test_mixed_requires_returns_only_the_unmet_ones(tmp_path):
    # scheduling fully present, visual absent -> only visual is reported missing.
    (tmp_path / "app" / "tools").mkdir(parents=True)
    (tmp_path / "app" / "db").mkdir(parents=True)
    (tmp_path / "app" / "tools" / "scheduling_tools.py").write_text("")
    (tmp_path / "app" / "db" / "models_scheduling.py").write_text("")
    assert gating.missing_requirements(["scheduling", "visual"], root=tmp_path) == ["visual"]


def test_missing_requirements_preserves_input_order(tmp_path):
    # Both unmet: the returned list mirrors the requested order (deterministic reporting).
    assert gating.missing_requirements(["visual", "scheduling"], root=tmp_path) == [
        "visual",
        "scheduling",
    ]


def test_unknown_names_are_dropped_but_real_unmet_ones_survive(tmp_path):
    # A typo'd requirement is treated as satisfied (never gates forever) while a real,
    # unmet requirement in the same list is still reported.
    assert gating.missing_requirements(["typo_feature", "scheduling"], root=tmp_path) == [
        "scheduling"
    ]


def test_is_available_is_false_when_any_requirement_unmet(tmp_path):
    assert gating.is_available(["scheduling"], root=tmp_path) is False
    assert gating.is_available(["scheduling", "visual"], root=tmp_path) is False


def test_is_available_is_true_for_empty_and_unknown_requires(tmp_path):
    assert gating.is_available([], root=tmp_path) is True
    assert gating.is_available(["not_a_real_feature"], root=tmp_path) is True


def test_is_available_true_once_all_sentinels_present(tmp_path):
    (tmp_path / "app" / "tools").mkdir(parents=True)
    (tmp_path / "app" / "db").mkdir(parents=True)
    (tmp_path / "app" / "tools" / "visual_tools.py").write_text("")
    (tmp_path / "app" / "db" / "models_visual.py").write_text("")
    assert gating.is_available(["visual"], root=tmp_path) is True


def test_gating_signal_is_path_existence_not_file_type(tmp_path):
    # Gating checks path *existence*, so guard that a stray directory at the sentinel's
    # path still resolves via .exists() (documents the file-vs-dir tolerance of the signal).
    sentinel = tmp_path / "app" / "tools" / "scheduling_tools.py"
    sentinel.mkdir(parents=True)  # a directory, not a file, at the sentinel path
    (tmp_path / "app" / "db").mkdir(parents=True)
    (tmp_path / "app" / "db" / "models_scheduling.py").write_text("")
    # .exists() is true for the directory, so the feature reads as merged. This test
    # pins that documented behavior so a future switch to is_file() is a conscious change.
    assert gating.missing_requirements(["scheduling"], root=tmp_path) == []
