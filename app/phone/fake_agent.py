"""Stub agent for standalone phone-bridge development (COORDINATION.md §4).

``voice-diagnostic-core`` owns the real LlamaIndex ``FunctionAgent``; this feature does
not need it to build and test the webhook/codec/VAD/bridge. ``FakeAgent`` stands in as
the turn-driver the bridge calls: given inbound text and the bridge (which implements
``app.contracts.SessionBridge``), it produces a scripted reply and pushes it back out
through the bridge's own ``emit_transcript``/``emit_audio``.

Integration note (COORDINATION §5 step 5): swapping in the real agent means giving it
something with this same ``async handle_turn(text, bridge)`` shape -- e.g. a thin
adapter around ``AgentWorkflow.run`` that streams sentence chunks into
``bridge.emit_transcript("agent", ...)`` / ``bridge.emit_audio(...)`` as they're
TTS-synthesized. That adapter is not this feature's to write; flagged in plan.md
Integration deltas.
"""

from __future__ import annotations

from collections.abc import Callable

from app.contracts import SessionBridge


class FakeAgent:
    """Echoes scripted replies in order (looping the last one once exhausted)."""

    def __init__(
        self,
        scripted_replies: list[str] | None = None,
        tts: Callable[[str], bytes] | None = None,
    ) -> None:
        self._replies = list(scripted_replies or ["Thanks, tell me more about that."])
        self._next_index = 0
        # A cheap stand-in "TTS": silent PCM16 (even byte count, so the codec's
        # resample/mu-law path accepts it) with a duration roughly proportional to the
        # reply length. Real synthesis is the agent feature's concern, not this stub's.
        self._tts = tts or (lambda text: b"\x00\x00" * max(160, len(text) * 40))

    async def handle_turn(self, text: str, bridge: SessionBridge) -> None:
        reply = self._replies[min(self._next_index, len(self._replies) - 1)]
        self._next_index += 1
        await bridge.emit_transcript("agent", reply)
        await bridge.emit_audio(self._tts(reply))
