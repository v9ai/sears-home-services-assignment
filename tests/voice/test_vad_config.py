"""`VAD_STOP_SECS` knob tests for `app.voice.bot._build_vad_analyzer` — the stop
hangover is pure dead air inside the phone latency envelope, so its default and safe
floor are recorded centrally (`app/latency/budgets.py`) and guarded here.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("pipecat.audio.vad.silero")

from app.latency.budgets import VAD_STOP_SECS_DEFAULT, VAD_STOP_SECS_MIN_SAFE  # noqa: E402
from app.voice.bot import _build_vad_analyzer  # noqa: E402


def test_vad_stop_secs_default(monkeypatch):
    monkeypatch.delenv("VAD_STOP_SECS", raising=False)
    analyzer = _build_vad_analyzer()
    assert analyzer.params.stop_secs == VAD_STOP_SECS_DEFAULT


def test_vad_stop_secs_env_override(monkeypatch):
    monkeypatch.setenv("VAD_STOP_SECS", "0.45")
    analyzer = _build_vad_analyzer()
    assert analyzer.params.stop_secs == 0.45


def test_vad_stop_secs_below_floor_logs_and_honors(monkeypatch, caplog):
    """An override below the safe floor is honored (an operator override stays an
    override) but must be observable — the false-end-of-turn risk gets logged."""
    monkeypatch.setenv("VAD_STOP_SECS", "0.2")
    with caplog.at_level(logging.INFO, logger="app.voice.bot"):
        analyzer = _build_vad_analyzer()
    assert analyzer.params.stop_secs == 0.2  # honored, not clamped
    assert "event=voice.vad.stop_secs_below_safe_floor" in caplog.text
    assert f"min_safe={VAD_STOP_SECS_MIN_SAFE}" in caplog.text


def test_vad_stop_secs_at_floor_does_not_log(monkeypatch, caplog):
    monkeypatch.setenv("VAD_STOP_SECS", str(VAD_STOP_SECS_MIN_SAFE))
    with caplog.at_level(logging.INFO, logger="app.voice.bot"):
        _build_vad_analyzer()
    assert "stop_secs_below_safe_floor" not in caplog.text
