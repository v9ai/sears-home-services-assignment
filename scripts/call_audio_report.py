"""Offline call-audio stutter analyzer (stutter-iterate q2) — live evidence extractor.

The stutter bench (`scripts/stutter_bench.py`) proves the guards hermetically; this
tool turns REAL calls into ledger-able evidence. It reads the per-call stereo
recording (`{RECORDINGS_DIR}/{session_id}/call.wav`, caller = left / bot = right —
`app/voice/recording.py::write_stereo_wav`) and inspects the BOT channel for the two
audible signatures of the barge-in echo loop (docs/local-twilio-run.md "Stuttering
during the reply"):

- **mid-reply gaps** — silences > 250 ms INSIDE one bot reply (a Twilio ``clear``
  chops the reply; the pause before the restart is the audible gap);
- **restarts** — the audio right after a mid-reply gap strongly correlates with the
  audio right before it (the flushed reply re-streams from the same sentence).

Per call it prints one JSON verdict: ``clean`` or ``stutter-suspect`` with the gap
timestamps, so a loop iteration (or a human) can say "call CAxxxx stuttered at
12.4 s" instead of "it sounded bad". Usage:

    python scripts/call_audio_report.py                # scan RECORDINGS_DIR for */call.wav
    python scripts/call_audio_report.py path/to/a.wav  # analyze specific file(s)

Exit code 0 always — an analyzer must never fail a pipeline; absence of recordings is
itself a (reported) result.
"""

from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

RECORDINGS_DIR = Path(os.environ.get("RECORDINGS_DIR", "data/recordings"))
CALL_AUDIO_FILENAME = "call.wav"

FRAME_S = 0.02  # 20 ms analysis frames
# Silence shorter than this inside a reply is normal prosody; longer is a suspect gap.
MIDREPLY_GAP_S = 0.25
# Silence at least this long separates two REPLIES (turn-taking), not a mid-reply gap.
REPLY_SPLIT_SILENCE_S = 1.0
# Correlation window around a gap for restart detection, and its decision threshold.
RESTART_WINDOW_S = 0.3
RESTART_CORR_THRESHOLD = 0.7
# How far back into the reply the post-gap head is searched for a replayed match.
RESTART_SEARCH_S = 5.0
# Speech activity: a frame is active when its RMS clears max(abs floor, 5% of peak).
RMS_FLOOR = 150.0
RMS_PEAK_FRACTION = 0.05


def read_bot_channel(path: Path) -> tuple[np.ndarray, int]:
    """Bot samples as float64 in [-1, 1] + sample rate. Right channel when stereo;
    a mono file is analyzed as-is (older per-line recordings)."""
    with wave.open(str(path), "rb") as wav_file:
        rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        pcm = wav_file.readframes(wav_file.getnframes())
    samples = np.frombuffer(pcm, dtype=np.int16)
    if channels == 2:
        samples = samples[1::2]  # caller = left (0), bot = right (1)
    return samples.astype(np.float64) / 32768.0, rate


def _frame_rms(samples: np.ndarray, rate: int) -> np.ndarray:
    hop = int(rate * FRAME_S)
    n_frames = len(samples) // hop
    if n_frames == 0:
        return np.zeros(0)
    frames = samples[: n_frames * hop].reshape(n_frames, hop)
    return np.sqrt((frames**2).mean(axis=1))


def _active_runs(active: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) frame-index runs of consecutive True."""
    runs: list[tuple[int, int]] = []
    start = None
    for i, is_active in enumerate(active):
        if is_active and start is None:
            start = i
        elif not is_active and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(active)))
    return runs


def _restart_correlation(
    samples: np.ndarray,
    rate: int,
    reply_start_s: float,
    gap_start_s: float,
    gap_end_s: float,
) -> float:
    """Peak normalized cross-correlation of the post-gap head against the pre-gap
    part of the SAME reply. A flushed-and-restarted reply re-streams audio it already
    played (usually from the start of the interrupted sentence, not the exact cut
    point), so the post-gap window is searched across the whole pre-gap region."""
    window = int(rate * RESTART_WINDOW_S)
    search_start = int(max(reply_start_s, gap_start_s - RESTART_SEARCH_S) * rate)
    search = samples[search_start : int(gap_start_s * rate)]
    post = samples[int(gap_end_s * rate) : int(gap_end_s * rate) + window]
    if len(post) < window or len(search) < window:
        return 0.0
    corr = np.correlate(search, post, mode="valid")
    post_norm = np.linalg.norm(post)
    squares = np.concatenate([[0.0], np.cumsum(search**2)])
    segment_norms = np.sqrt(squares[window:] - squares[:-window])
    denom = segment_norms * post_norm
    valid = denom > 1e-9
    if not valid.any():
        return 0.0
    return float((corr[valid] / denom[valid]).max())


def analyze_bot_audio(samples: np.ndarray, rate: int) -> dict:
    """Gap/restart analysis of one bot-channel signal (pure; unit-testable)."""
    rms = _frame_rms(samples, rate)
    if len(rms) == 0:
        return {
            "duration_s": 0.0,
            "replies": 0,
            "midreply_gaps": [],
            "suspected_restarts": 0,
            "verdict": "clean",
        }
    threshold = max(RMS_FLOOR / 32768.0, RMS_PEAK_FRACTION * float(rms.max()))
    active = rms > threshold
    runs = _active_runs(active)

    split_frames = int(REPLY_SPLIT_SILENCE_S / FRAME_S)
    gap_frames = int(MIDREPLY_GAP_S / FRAME_S)

    replies = 0
    midreply_gaps: list[dict] = []
    prev_end: int | None = None
    reply_start_frame = 0
    for start, end in runs:
        if prev_end is None or (start - prev_end) >= split_frames:
            replies += 1  # long silence (or first speech) → a new reply
            reply_start_frame = start
        elif (start - prev_end) >= gap_frames:
            gap_start_s = prev_end * FRAME_S
            gap_end_s = start * FRAME_S
            corr = _restart_correlation(
                samples, rate, reply_start_frame * FRAME_S, gap_start_s, gap_end_s
            )
            midreply_gaps.append(
                {
                    "at_s": round(gap_start_s, 2),
                    "gap_ms": round((gap_end_s - gap_start_s) * 1000),
                    "restart_correlation": round(corr, 2),
                    "suspected_restart": corr >= RESTART_CORR_THRESHOLD,
                }
            )
        prev_end = end

    suspected_restarts = sum(1 for g in midreply_gaps if g["suspected_restart"])
    return {
        "duration_s": round(len(samples) / rate, 2),
        "replies": replies,
        "midreply_gaps": midreply_gaps,
        "suspected_restarts": suspected_restarts,
        "verdict": "stutter-suspect" if midreply_gaps else "clean",
    }


def analyze_file(path: Path) -> dict:
    samples, rate = read_bot_channel(path)
    report = analyze_bot_audio(samples, rate)
    report["file"] = str(path)
    report["sample_rate"] = rate
    return report


def find_call_recordings() -> list[Path]:
    return sorted(RECORDINGS_DIR.glob(f"*/{CALL_AUDIO_FILENAME}"))


def main(argv: list[str]) -> None:
    paths = [Path(p) for p in argv] if argv else find_call_recordings()
    if not paths:
        print(
            json.dumps(
                {"calls_analyzed": 0, "note": f"no {CALL_AUDIO_FILENAME} under {RECORDINGS_DIR}"}
            )
        )
        return
    suspect = 0
    for path in paths:
        report = analyze_file(path)
        suspect += report["verdict"] == "stutter-suspect"
        print(json.dumps(report))
    summary = {
        "calls_analyzed": len(paths),
        "stutter_suspect": suspect,
        "clean": len(paths) - suspect,
    }
    print(json.dumps(summary))


if __name__ == "__main__":
    main(sys.argv[1:])
