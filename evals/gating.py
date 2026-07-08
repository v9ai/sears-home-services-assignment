"""Feature-availability gating for `requires:`-marked scenarios (COORDINATION.md §4).

A scenario's ``requires: [scheduling|visual]`` names a sibling feature triplet that
may not have merged yet. We treat "merged" as "its owned files exist on disk" — the
same file-presence signal the tool auto-discovery registry (`app/tools/registry.py`)
relies on implicitly. This module never imports the sibling feature's code (and never
imports `app.agent`); it only checks paths.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Relative to a repo root. A feature counts as "merged" once every one of its
# sentinel files exists.
_SENTINELS: dict[str, list[str]] = {
    "scheduling": [
        "app/tools/scheduling_tools.py",
        "app/db/models_scheduling.py",
    ],
    "visual": [
        "app/tools/visual_tools.py",
        "app/db/models_visual.py",
    ],
}


def missing_requirements(requires: list[str], root: Path | None = None) -> list[str]:
    """Return the subset of `requires` whose sentinel files are not yet present.

    Unknown requirement names (no registered sentinel) are never gated — treat them
    as satisfied rather than silently blocking a scenario forever on a typo. `root`
    defaults to the repo root; tests pass a `tmp_path` to stay independent of the
    actual worktree's merge state.
    """
    root = root or REPO_ROOT
    missing: list[str] = []
    for feature in requires:
        sentinels = _SENTINELS.get(feature)
        if not sentinels:
            continue
        if not all((root / rel).exists() for rel in sentinels):
            missing.append(feature)
    return missing


def is_available(requires: list[str], root: Path | None = None) -> bool:
    return not missing_requirements(requires, root=root)
