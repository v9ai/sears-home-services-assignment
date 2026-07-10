"""Guards for the q0-3 eval-gate split (loop v2): hermetic (mandatory) vs live
(advisory) eval lanes. Static + collection checks only — no judge keys, no network.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_live_marker_registered():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert "live: drives the real agent/LLM" in pyproject, (
        "the `live` pytest marker must stay registered (q0-3 split)"
    )


def test_library_live_module_is_marked_live():
    text = (REPO_ROOT / "evals" / "test_library_live.py").read_text()
    assert "pytestmark = pytest.mark.live" in text, (
        "live agent drives must carry the live marker or they leak into the "
        "MANDATORY hermetic eval lane"
    )


def test_makefile_has_split_targets():
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert 'pytest evals -q -m "not live"' in makefile  # hermetic = hard lane
    assert "pytest evals -q -m live" in makefile  # live = advisory lane
    assert "--last-failed" in makefile  # advisory retry-once
    assert "eval: eval-hermetic eval-live" in makefile


def test_hermetic_lane_deselects_live_tests():
    """`-m 'not live'` must exclude every live drive; `-m live` must catch them.
    Collection only — runs keyless in ~2s."""
    collect = subprocess.run(
        [sys.executable, "-m", "pytest", "evals", "-q", "-m", "not live", "--collect-only"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert "test_library_live" not in collect.stdout, "live test leaked into the hermetic lane"

    live_collect = subprocess.run(
        [sys.executable, "-m", "pytest", "evals", "-q", "-m", "live", "--collect-only"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert "test_library_live" in live_collect.stdout, "live lane lost its tests"
