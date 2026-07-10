"""Hermetic stutter bench — the phone-audio-quality loop's metric (stutter-iterate q1).

Four keyless probes encode the 2026-07-09 barge-in echo-loop RCA
(docs/local-twilio-run.md "Stuttering during the reply"): an AEC-less PSTN leg returns
the bot's own TTS on the inbound stream; anything that lets that echo open a user turn
fires interruption → Twilio ``clear`` → the reply is flushed and restarts → stutter.
A live PSTN call cannot be automated, so the bench drives the production guard,
serializer, and output transport in-process instead:

- ``echo_storm``      — echo-shaped transcriptions while the bot speaks must open 0
                        turns AND a genuine talk-over must still barge in (the
                        anti-overcorrection invariant lives inside the metric).
- ``clear_accounting``— Twilio ``clear``s counted == genuine interruptions, exactly.
- ``phantom_tail``    — trailing echo right after the bot stops (advisory until the
                        echo-tail guard lands; ``PHANTOM_TAIL_ENFORCED`` flips then).
- ``pacing``          — outbound media-frame cadence through the REAL
                        FastAPIWebsocketTransport + SafeTwilioFrameSerializer with a
                        stub websocket; 3 runs, median + noise_pct (timing is noisy —
                        never judged on one sample).

Writes ``data/stutter/<utc-ts>.json`` (schema below) and prints a one-line verdict per
probe. HARD GATE since the loop's gate-flip (2026-07-10): a failing report exits 1
(``STUTTER_GATE_HARD=0`` reverts to report-only), and ``make test`` runs the bench
first. Probes measure the repo's PRODUCTION DEFAULTS: guard env knobs
(``VOICE_BARGEIN_*``, ``VOICE_OUT_10MS_CHUNKS``) are cleared for the process so an
operator's shell can't skew the report.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
OUT_DIR = Path(os.environ.get("STUTTER_BENCH_DIR", "data/stutter"))

# The documented echo-hallucination shapes (docs/local-twilio-run.md): short 1-2 word
# fragments transcribed from the bot's own returned TTS audio.
ECHO_SHAPES = ("Wow.", "watch.", "thank you", "sushi.", "Okay.", "hm yes")
GENUINE_BARGE_IN = "wait stop I have a question"
TAIL_ECHO = "Wow."

# Flipped to True by the echo-tail guard fix (stutter-loop f1, 2026-07-10) — a tail
# echo opening a turn now FAILS the bench, and the caller's quick one-word answer
# arriving AFTER the tail window must still open a turn (anti-overcorrection).
PHANTOM_TAIL_ENFORCED = True

PACING_RUNS = 3
PACING_SECONDS = float(os.environ.get("STUTTER_PACING_SECONDS", "2.0"))
PACING_MAX_GAP_BUDGET_MS = 120.0  # generous: catches blocking regressions, not CI jitter
PACING_MIN_SENDS = 20  # fewer sends than this = the probe itself is broken

_BENCH_TS = "2026-01-01T00:00:00Z"  # frame timestamps are inert metadata here


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _bench_serializer(cls):
    """Serializer with auto-hangup OFF (pipecat 1.5 raises on missing creds otherwise);
    nothing must leave the box during a bench run."""
    from pipecat.serializers.twilio import TwilioFrameSerializer

    return cls(
        stream_sid="MZbench",
        call_sid=None,
        account_sid="",
        auth_token="",
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )


def _strategy_with_recorder():
    """Production guard + a recorder on its turn-started event."""
    from app.voice.bot import _build_user_turn_strategies

    strategies = _build_user_turn_strategies()
    if strategies is None:  # guard disabled — the bench measures defaults, so this fails
        return None, None
    (strategy,) = strategies.start
    started: list = []

    async def _on_started(_strategy, params) -> None:
        started.append(params)

    strategy.add_event_handler("on_user_turn_started", _on_started)
    return strategy, started


async def probe_echo_storm() -> dict:
    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        InterimTranscriptionFrame,
        TranscriptionFrame,
    )

    budget = {"echo_turns_opened": 0, "genuine_bargein_honored": True}
    strategy, started = _strategy_with_recorder()
    if strategy is None:
        return {
            "echo_events_injected": len(ECHO_SHAPES),
            "echo_turns_opened": None,
            "genuine_bargein_honored": False,
            "guard_disabled": True,
            "budget": budget,
            "pass": False,
        }

    await strategy.process_frame(BotStartedSpeakingFrame())
    for text in ECHO_SHAPES:
        await strategy.process_frame(
            InterimTranscriptionFrame(text=text, user_id="caller", timestamp=_BENCH_TS)
        )
        await strategy.process_frame(
            TranscriptionFrame(text=text, user_id="caller", timestamp=_BENCH_TS)
        )
    echo_turns_opened = len(started)

    await strategy.process_frame(
        TranscriptionFrame(text=GENUINE_BARGE_IN, user_id="caller", timestamp=_BENCH_TS)
    )
    genuine_bargein_honored = len(started) == echo_turns_opened + 1

    return {
        "echo_events_injected": len(ECHO_SHAPES),
        "echo_turns_opened": echo_turns_opened,
        "genuine_bargein_honored": genuine_bargein_honored,
        "budget": budget,
        "pass": echo_turns_opened == 0 and genuine_bargein_honored,
    }


async def probe_clear_accounting(genuine_interruptions: int = 1) -> dict:
    """One serialized ``clear`` per genuine interruption — no phantoms, none missing."""
    from pipecat.frames.frames import InterruptionFrame

    from app.voice.serializer import SafeTwilioFrameSerializer

    serializer = _bench_serializer(SafeTwilioFrameSerializer)
    for _ in range(genuine_interruptions):
        await serializer.serialize(InterruptionFrame())
    clears_sent = serializer.bargein_clears

    return {
        "clears_sent": clears_sent,
        "genuine_interruptions": genuine_interruptions,
        "budget": {"excess_clears": 0},
        "pass": clears_sent == genuine_interruptions,
    }


async def probe_phantom_tail() -> dict:
    """Trailing echo: bot stops, its last words come back ~immediately as a 1-word
    transcription. The echo-tail guard (f1) must hold the word bar through the tail
    window — AND a quick one-word real answer AFTER the window must still open a turn
    (the anti-overcorrection half of the probe; costs one real tail-length sleep)."""
    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
        TranscriptionFrame,
    )

    from app.voice.bot import VOICE_BARGEIN_TAIL_MS_DEFAULT

    budget = {"tail_echo_turns_opened": 0, "post_window_turn_opened": True}
    strategy, started = _strategy_with_recorder()
    if strategy is None:
        return {
            "tail_echo_turns_opened": None,
            "post_window_turn_opened": False,
            "enforced": PHANTOM_TAIL_ENFORCED,
            "guard_disabled": True,
            "budget": budget,
            "pass": False,
        }

    await strategy.process_frame(BotStartedSpeakingFrame())
    await strategy.process_frame(BotStoppedSpeakingFrame())
    await strategy.process_frame(
        TranscriptionFrame(text=TAIL_ECHO, user_id="caller", timestamp=_BENCH_TS)
    )
    tail_echo_turns_opened = len(started)

    # Past the tail window the caller's quick "yes" must land (production clock, so
    # actually wait it out — the probe measures the real default configuration).
    await asyncio.sleep(VOICE_BARGEIN_TAIL_MS_DEFAULT / 1000 + 0.05)
    await strategy.process_frame(
        TranscriptionFrame(text="yes", user_id="caller", timestamp=_BENCH_TS)
    )
    post_window_turn_opened = len(started) == tail_echo_turns_opened + 1

    passed = post_window_turn_opened and (
        tail_echo_turns_opened == 0 if PHANTOM_TAIL_ENFORCED else True
    )
    return {
        "tail_echo_turns_opened": tail_echo_turns_opened,
        "post_window_turn_opened": post_window_turn_opened,
        "enforced": PHANTOM_TAIL_ENFORCED,
        "budget": budget,
        "pass": passed,
    }


async def _pacing_once() -> dict:
    """Drive ~PACING_SECONDS of 8 kHz silence through the REAL output transport +
    Twilio serializer; record wall-clock send instants at the (stubbed) websocket."""
    from pipecat.frames.frames import OutputAudioRawFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineParams
    from pipecat.tests.utils import run_test
    from pipecat.transports.websocket.fastapi import (
        FastAPIWebsocketTransport,
    )
    from starlette.websockets import WebSocketState

    from app.voice.bot import TWILIO_SAMPLE_RATE
    from app.voice.serializer import SafeTwilioFrameSerializer

    class _StubWebsocket:
        """The minimal surface FastAPIWebsocketClient touches on the send path."""

        def __init__(self) -> None:
            self.client_state = WebSocketState.CONNECTED
            self.application_state = WebSocketState.CONNECTED
            self.send_times: list[float] = []

        async def send_text(self, _data: str) -> None:
            self.send_times.append(time.monotonic())

        async def send_bytes(self, _data: bytes) -> None:
            self.send_times.append(time.monotonic())

        async def close(self, code: int = 1000, reason: str | None = None) -> None:
            self.client_state = WebSocketState.DISCONNECTED

    websocket = _StubWebsocket()
    serializer = _bench_serializer(SafeTwilioFrameSerializer)
    # Production-faithful params (f2): the same builder run_bot uses, so the probe
    # measures the real framing (VOICE_OUT_10MS_CHUNKS default = 20 ms cadence).
    from app.voice.bot import _build_transport_params

    transport = FastAPIWebsocketTransport(
        websocket=websocket,  # type: ignore[arg-type] — stub covers the send surface
        params=_build_transport_params(serializer),
    )

    # 200 ms producer frames; the transport re-chunks to its own cadence
    # (audio_out_10ms_chunks × 10 ms) and paces each send.
    frame_bytes = int(TWILIO_SAMPLE_RATE * 2 * 0.2)
    frames = [
        OutputAudioRawFrame(
            audio=b"\x00" * frame_bytes, sample_rate=TWILIO_SAMPLE_RATE, num_channels=1
        )
        for _ in range(int(PACING_SECONDS / 0.2))
    ]
    await run_test(
        Pipeline([transport.output()]),
        frames_to_send=frames,
        expected_down_frames=None,
        pipeline_params=PipelineParams(
            audio_in_sample_rate=TWILIO_SAMPLE_RATE,
            audio_out_sample_rate=TWILIO_SAMPLE_RATE,
        ),
    )

    times = websocket.send_times
    intervals_ms = [(b - a) * 1000 for a, b in zip(times, times[1:], strict=False)]
    cadence_ms = transport.output().audio_chunk_size / (TWILIO_SAMPLE_RATE * 2) * 1000
    return {
        "sends": len(times),
        "cadence_ms": cadence_ms,
        "intervals_ms": intervals_ms,
    }


async def probe_pacing() -> dict:
    from app.voice.bot import VOICE_OUT_10MS_CHUNKS_DEFAULT

    expected_cadence_ms = VOICE_OUT_10MS_CHUNKS_DEFAULT * 10
    runs = [await _pacing_once() for _ in range(PACING_RUNS)]
    cadence_ms = runs[0]["cadence_ms"]
    max_gaps = [max(r["intervals_ms"], default=0.0) for r in runs]
    p95s = [
        statistics.quantiles(r["intervals_ms"], n=20)[-1] if len(r["intervals_ms"]) >= 20 else 0.0
        for r in runs
    ]
    gap_counts = [sum(1 for i in r["intervals_ms"] if i > 2 * cadence_ms) for r in runs]
    max_gap_median = statistics.median(max_gaps)
    noise_pct = (max(max_gaps) - min(max_gaps)) / max_gap_median * 100 if max_gap_median else 0.0
    min_sends = min(r["sends"] for r in runs)
    budget = {
        "cadence_ms": expected_cadence_ms,
        "max_gap_ms_median": PACING_MAX_GAP_BUDGET_MS,
        "gaps_over_2x_cadence_median": 0,
    }
    integrity_ok = min_sends >= PACING_MIN_SENDS and cadence_ms == expected_cadence_ms
    return {
        "cadence_ms": cadence_ms,
        "runs": PACING_RUNS,
        "sends_min": min_sends,
        "frame_interval_p95_ms": round(statistics.median(p95s), 2),
        "max_gap_ms_median": round(max_gap_median, 2),
        "noise_pct": round(noise_pct, 1),
        "gaps_over_2x_cadence_median": int(statistics.median(gap_counts)),
        "budget": budget,
        "pass": (
            integrity_ok
            and max_gap_median <= PACING_MAX_GAP_BUDGET_MS
            and int(statistics.median(gap_counts)) <= 0
        ),
    }


def build_report(probes: dict[str, dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp_utc": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "probes": probes,
        "overall_pass": all(p.get("pass") for p in probes.values()),
    }


async def run_bench() -> dict:
    echo_storm = await probe_echo_storm()
    probes = {
        "echo_storm": echo_storm,
        # 1 genuine interruption — the storm scenario's honored barge-in.
        "clear_accounting": await probe_clear_accounting(genuine_interruptions=1),
        "phantom_tail": await probe_phantom_tail(),
        "pacing": await probe_pacing(),
    }
    return build_report(probes)


def main() -> None:
    # Bench-of-defaults: operator env must not skew the production-default measurement.
    for knob in ("VOICE_BARGEIN_MIN_WORDS", "VOICE_BARGEIN_TAIL_MS", "VOICE_OUT_10MS_CHUNKS"):
        os.environ.pop(knob, None)

    report = asyncio.run(run_bench())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{_utc_now().strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n")

    for name, probe in report["probes"].items():
        verdict = "PASS" if probe["pass"] else "FAIL"
        extra = " (advisory)" if name == "phantom_tail" and not probe["enforced"] else ""
        print(f"stutter-bench {name}: {verdict}{extra}")
    print(f"stutter-bench overall: {'PASS' if report['overall_pass'] else 'FAIL'} -> {out_path}")

    # Hard gate (stutter-loop gate-flip, 2026-07-10): earned by probes PASSing across
    # the whole loop; STUTTER_GATE_HARD=0 is the report-only escape hatch.
    if not report["overall_pass"] and os.environ.get("STUTTER_GATE_HARD", "1") == "1":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
