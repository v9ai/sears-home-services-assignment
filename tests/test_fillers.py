from __future__ import annotations

import os

from app.agent import fillers
from app.agent.prompts import GREETING
from app.ws import routes as ws_routes


def test_cached_strings_non_empty_and_distinct():
    assert len(fillers.CACHED_STRINGS) == 4
    assert all(s.strip() for s in fillers.CACHED_STRINGS)
    assert len(set(fillers.CACHED_STRINGS)) == len(fillers.CACHED_STRINGS)


def test_web_module_imports_shared_constants():
    assert ws_routes.TOOL_CALL_FILLER is fillers.WEB_TOOL_FILLER
    assert ws_routes.TURN_FAILED_FALLBACK is fillers.WEB_TURN_FAILED_FALLBACK


def test_filler_debounce_default():
    assert fillers.FILLER_DEBOUNCE_S == 0.25


# --- Filler policy: what the shared constants must guarantee -------------------------


def test_tool_filler_is_not_the_failure_fallback():
    # The "let me check that" filler is spoken to cover latency on a normal turn; the
    # fallback is an error apology. Conflating them would speak an error over a healthy
    # turn — they must stay distinct strings.
    assert fillers.WEB_TOOL_FILLER != fillers.WEB_TURN_FAILED_FALLBACK
    assert fillers.PHONE_TOOL_FILLER != fillers.WEB_TURN_FAILED_FALLBACK


def test_greeting_is_prewarmed_so_it_speaks_with_zero_synth_latency():
    # The greeting is the very first thing a caller hears; it must be in the prewarm set
    # so it's served from the TTS cache instead of paying a cold synth on connect.
    assert GREETING in fillers.CACHED_STRINGS


def test_both_tool_fillers_are_prewarmed():
    assert fillers.PHONE_TOOL_FILLER in fillers.CACHED_STRINGS
    assert fillers.WEB_TOOL_FILLER in fillers.CACHED_STRINGS


def test_web_and_phone_tool_fillers_are_channel_specific():
    # Same purpose, deliberately different wording per channel (fillers.py docstring) —
    # the web variant trails off with an ellipsis for the text UI.
    assert fillers.WEB_TOOL_FILLER != fillers.PHONE_TOOL_FILLER
    assert fillers.WEB_TOOL_FILLER.startswith(fillers.PHONE_TOOL_FILLER.rstrip("."))


def test_debounce_is_positive_and_subsecond():
    # The debounce is the "never double-fire" guard: short enough to still cover real
    # latency, but a real interval so two fillers can't stack on one turn.
    assert 0 < fillers.FILLER_DEBOUNCE_S < 1


def test_debounce_derives_from_the_env_default():
    # Mirrors the module's own `FILLER_DEBOUNCE_MS / 1000` derivation at import time.
    expected_ms = float(os.environ.get("FILLER_DEBOUNCE_MS", "250"))
    assert fillers.FILLER_DEBOUNCE_S == expected_ms / 1000


def test_fallback_reads_as_a_recoverable_apology_not_a_dead_end():
    # The turn-failed fallback must invite the caller to continue (re-say / rephrase),
    # not terminate the call — it's spoken only when a turn errored before any content.
    text = fillers.WEB_TURN_FAILED_FALLBACK.lower()
    assert "again" in text or "rephrase" in text


# --- Filler debounce gate (should_fire_filler) --------------------------------------
# The web bridge (app/ws/routes.py) fires the tool-call filler every turn; the debounce
# stops rapid consecutive turns from stacking overlapping "let me check that" clips.


def test_first_filler_always_fires():
    # No prior filler this session — the very first turn must always get one, whatever
    # the clock reads.
    assert fillers.should_fire_filler(None, now=0.0) is True
    assert fillers.should_fire_filler(None, now=123456.0) is True


def test_filler_suppressed_within_the_debounce_window():
    last = 100.0
    within = last + fillers.FILLER_DEBOUNCE_S / 2
    assert fillers.should_fire_filler(last, now=within) is False


def test_filler_fires_again_after_the_window_elapses():
    last = 100.0
    after = last + fillers.FILLER_DEBOUNCE_S + 0.01
    assert fillers.should_fire_filler(last, now=after) is True


def test_filler_fires_exactly_at_the_window_boundary():
    # The gate is `>= debounce_s`, so a turn landing exactly one window later fires.
    last = 100.0
    assert fillers.should_fire_filler(last, now=last + fillers.FILLER_DEBOUNCE_S) is True


def test_debounce_window_is_configurable_per_call():
    # A caller can pass its own window (the constant is only the default).
    assert fillers.should_fire_filler(10.0, now=10.4, debounce_s=0.5) is False
    assert fillers.should_fire_filler(10.0, now=10.6, debounce_s=0.5) is True


def test_rapid_burst_lets_through_only_one_filler_per_window():
    """Simulate the routes.py fire loop over a controlled clock: three turns inside one
    window yield exactly one filler; a fourth past the window yields a second."""
    last_filler_at: float | None = None
    fired: list[float] = []

    def turn(now: float) -> None:
        nonlocal last_filler_at
        # Mirror the routes.py gate: stamp the fire time only when a filler fires.
        if fillers.should_fire_filler(last_filler_at, now):
            last_filler_at = now
            fired.append(now)

    step = fillers.FILLER_DEBOUNCE_S / 3
    base = 1000.0
    turn(base)  # first — fires
    turn(base + step)  # within window — suppressed
    turn(base + 2 * step)  # still within window — suppressed
    turn(base + fillers.FILLER_DEBOUNCE_S + 0.01)  # past window — fires

    assert fired == [base, base + fillers.FILLER_DEBOUNCE_S + 0.01]


def test_session_state_carries_a_last_filler_timestamp_defaulting_none():
    # The debounce needs per-session state; SessionState must expose it, unset by default
    # (a fresh session's first turn always fires) and not persisted.
    import uuid

    from app.agent.session_store import SessionState
    from app.contracts import CaseFile

    state = SessionState(
        session_id=uuid.uuid4(),
        case_file=CaseFile(),
        memory=None,  # type: ignore[arg-type]  # not exercised here
    )
    assert state.last_filler_at is None


def test_phone_filler_path_does_not_use_the_web_debounce():
    # The phone FillerProcessor gates itself (its own _fired_this_turn + delay), so the
    # web-only debounce must not leak into it — a regression guard against someone wiring
    # should_fire_filler / FILLER_DEBOUNCE_S into the phone path by mistake.
    import inspect

    from app.voice import processors

    source = inspect.getsource(processors)
    assert "should_fire_filler" not in source
    assert "FILLER_DEBOUNCE_S" not in source
    # Its own per-turn gate still exists.
    assert "_fired_this_turn" in source
