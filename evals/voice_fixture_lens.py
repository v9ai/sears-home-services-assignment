"""Voice-channel lens over a recorded fixture transcript.

The Pipecat voice channel speaks its replies through TTS, so the caller hears the
`SpokenTextSanitizer`-cleaned form of every agent turn (`app/voice/text.sanitize_for_speech`),
not the raw model text. `voice_lens` applies exactly that transform to a fixture so the
DeepEval conversational gate (`evals/test_voice_conversations.py`) scores what the caller
would actually *hear* on the phone — proving persona/retention/safety survive the spoken
cleanup. It is a pure fixture→fixture transform (no `app.agent`, no live agent, no keys),
so it slots into the same recorded-fixture model `make eval` already uses.
"""

from __future__ import annotations

from typing import Any

from app.voice.text import sanitize_for_speech


def voice_lens(fixture: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `fixture` with each agent turn spoken-sanitized.

    Only agent turns are touched (that's what goes to TTS); user turns and the recorded
    `case_file`/`flags` are passed through unchanged — so the structural contract the
    scenario asserts on is preserved, and any regression would be a persona/wording one
    the judge catches.
    """
    turns = [
        {**turn, "text": sanitize_for_speech(turn["text"])} if turn.get("role") == "agent" else turn
        for turn in fixture.get("turns", [])
    ]
    return {**fixture, "turns": turns}
