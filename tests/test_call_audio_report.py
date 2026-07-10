"""Call-audio analyzer tests (stutter-iterate q2) — synthetic WAVs with known,
injected defects prove the detector finds exactly what it claims to find.

The analyzer extracts live evidence of the barge-in echo loop from real call
recordings: mid-reply gaps > 250 ms on the bot channel, and restarts (post-gap audio
correlating with pre-gap audio — a flushed reply re-streaming). These tests build
bot-channel signals from seeded noise (tones would correlate trivially, being
periodic) and assert each verdict."""

from __future__ import annotations

import json
import wave

import numpy as np
import pytest

from scripts import call_audio_report

RATE = 8000
RNG = np.random.default_rng(20260710)


def _noise(seconds: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.uniform(-0.5, 0.5, int(RATE * seconds))


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(RATE * seconds))


def _write_stereo(path, bot: np.ndarray) -> None:
    """caller = left (silence), bot = right — write_stereo_wav's channel layout."""
    caller = np.zeros_like(bot)
    interleaved = np.empty(2 * len(bot))
    interleaved[0::2] = caller
    interleaved[1::2] = bot
    pcm = (interleaved * 32767).astype(np.int16).tobytes()
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(RATE)
        wav_file.writeframes(pcm)


# --- analyze_bot_audio: the detector itself ----------------------------------------


def test_clean_two_replies_no_gaps():
    """Two replies separated by >= 1 s of turn-taking silence: no defects."""
    bot = np.concatenate([_noise(1.0, seed=1), _silence(2.0), _noise(1.0, seed=2)])
    report = call_audio_report.analyze_bot_audio(bot, RATE)
    assert report["replies"] == 2
    assert report["midreply_gaps"] == []
    assert report["verdict"] == "clean"


def test_midreply_gap_detected():
    """A 400 ms hole inside one reply (the audible chop) is flagged with its position."""
    bot = np.concatenate([_noise(1.0, seed=1), _silence(0.4), _noise(1.0, seed=2)])
    report = call_audio_report.analyze_bot_audio(bot, RATE)
    assert report["replies"] == 1  # 0.4 s < the 1 s reply-split: same reply
    assert len(report["midreply_gaps"]) == 1
    gap = report["midreply_gaps"][0]
    assert gap["at_s"] == pytest.approx(1.0, abs=0.05)
    assert gap["gap_ms"] == pytest.approx(400, abs=50)
    assert report["verdict"] == "stutter-suspect"


def test_restart_detected_when_post_gap_repeats_pre_gap():
    """The echo-loop signature: after the gap the reply re-streams the SAME audio."""
    segment = _noise(1.0, seed=7)
    bot = np.concatenate([segment, _silence(0.4), segment])
    report = call_audio_report.analyze_bot_audio(bot, RATE)
    assert len(report["midreply_gaps"]) == 1
    assert report["midreply_gaps"][0]["suspected_restart"] is True
    assert report["suspected_restarts"] == 1


def test_gap_without_repeat_is_not_a_restart():
    """Different audio after the gap = a pause, not a replay: gap yes, restart no."""
    bot = np.concatenate([_noise(1.0, seed=1), _silence(0.4), _noise(1.0, seed=99)])
    report = call_audio_report.analyze_bot_audio(bot, RATE)
    assert len(report["midreply_gaps"]) == 1
    assert report["midreply_gaps"][0]["suspected_restart"] is False
    assert report["suspected_restarts"] == 0


def test_short_prosody_pause_not_flagged():
    """A 150 ms breath inside a reply stays under the 250 ms gap threshold."""
    bot = np.concatenate([_noise(1.0, seed=1), _silence(0.15), _noise(1.0, seed=2)])
    report = call_audio_report.analyze_bot_audio(bot, RATE)
    assert report["midreply_gaps"] == []
    assert report["verdict"] == "clean"


def test_empty_audio_is_clean():
    report = call_audio_report.analyze_bot_audio(np.zeros(0), RATE)
    assert report["verdict"] == "clean"
    assert report["replies"] == 0


# --- file/CLI plumbing --------------------------------------------------------------


def test_analyze_file_reads_bot_from_right_channel(tmp_path):
    """Loud caller (left) + clean bot (right): defects on the caller channel must not
    leak into the bot verdict — the reader takes the right channel only."""
    bot = np.concatenate([_noise(1.0, seed=1), _silence(2.0), _noise(1.0, seed=2)])
    path = tmp_path / "call.wav"
    _write_stereo(path, bot)
    report = call_audio_report.analyze_file(path)
    assert report["file"] == str(path)
    assert report["sample_rate"] == RATE
    assert report["verdict"] == "clean"
    assert report["replies"] == 2


def test_main_scans_recordings_dir_and_prints_summary(tmp_path, monkeypatch, capsys):
    stuttery = np.concatenate([_noise(1.0, seed=7), _silence(0.4), _noise(1.0, seed=7)])
    call_dir = tmp_path / "CAfake"
    call_dir.mkdir()
    _write_stereo(call_dir / "call.wav", stuttery)
    monkeypatch.setattr(call_audio_report, "RECORDINGS_DIR", tmp_path)

    call_audio_report.main([])

    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert lines[0]["verdict"] == "stutter-suspect"
    assert lines[-1] == {"calls_analyzed": 1, "stutter_suspect": 1, "clean": 0}


def test_main_reports_absence_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(call_audio_report, "RECORDINGS_DIR", tmp_path / "nowhere")
    call_audio_report.main([])
    out = json.loads(capsys.readouterr().out.strip())
    assert out["calls_analyzed"] == 0
