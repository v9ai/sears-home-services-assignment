"""``/ws/twilio`` -- the Media Streams WebSocket endpoint.

Wires together the pieces owned by this feature: mu-law codec (:mod:`app.phone.codec`),
VAD turn segmentation (:mod:`app.phone.vad`), STT (:mod:`app.phone.stt`), the session
bridge (:mod:`app.phone.bridge`), and call metadata capture (:mod:`app.phone.call_context`).

Message loop per Twilio's Media Streams protocol (requirements.md "Contract shapes"):
``start`` (stream/call metadata) -> many ``media`` frames -> ``stop``. Barge-in: while
the bridge is mid-playback, any inbound frame that clears the VAD speech threshold
interrupts it immediately (send ``clear``, drop queued audio) before segmentation even
finishes a full turn -- responsiveness matters more than a clean cutoff there.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.phone.bridge import TurnAgent, TwilioMediaBridge
from app.phone.call_context import (
    InMemorySessionRecorder,
    PhoneCallContext,
    SessionRecorder,
)
from app.phone.codec import decode_b64_frame, mulaw_to_pcm16
from app.phone.fake_agent import FakeAgent
from app.phone.stt import Transcriber, get_transcriber
from app.phone.vad import TurnSegmenter, frame_is_speech

router = APIRouter()

AgentFactory = Callable[[], TurnAgent]


def _default_agent_factory() -> TurnAgent:
    # Stub seam (COORDINATION.md §4): the real agent swap-in is an integration step,
    # not this feature's -- see fake_agent.py's module docstring.
    return FakeAgent()


async def handle_twilio_media_stream(
    websocket: WebSocket,
    *,
    agent_factory: AgentFactory = _default_agent_factory,
    transcriber: Transcriber | None = None,
    session_recorder: SessionRecorder | None = None,
) -> TwilioMediaBridge:
    """Runs the full connection lifecycle; returns the bridge for post-hoc inspection
    (tests use this to assert on ``bridge.transcript`` / ``bridge.latency``)."""
    await websocket.accept()

    transcriber = transcriber or get_transcriber()
    session_recorder = session_recorder or InMemorySessionRecorder()

    bridge = TwilioMediaBridge(websocket, agent_factory())
    segmenter = TurnSegmenter()
    context = PhoneCallContext()

    async def _close_out_turn(pcm16: bytes | None) -> None:
        if not pcm16:
            return
        bridge.mark_end_of_speech()
        text = await transcriber.transcribe(pcm16, 8000)
        if text:
            await bridge.receive_user_utterance(text)

    try:
        while True:
            message = await websocket.receive_json()
            event = message.get("event")

            if event == "start":
                start = message.get("start", {})
                context.call_sid = start.get("callSid")
                context.stream_sid = start.get("streamSid") or message.get("streamSid")
                custom_params = start.get("customParameters", {}) or {}
                context.caller_number = custom_params.get("From")
                context.called_number = custom_params.get("To")
                bridge.bind_stream(context.stream_sid)
                await session_recorder.start_session(context)

            elif event == "media":
                payload = message.get("media", {}).get("payload", "")
                mulaw = decode_b64_frame(payload)
                pcm8k = mulaw_to_pcm16(mulaw)

                if bridge.is_playing and frame_is_speech(pcm8k):
                    await bridge.interrupt_playback()

                turn_pcm = segmenter.push(pcm8k)
                await _close_out_turn(turn_pcm)

            elif event == "stop":
                await _close_out_turn(segmenter.flush())
                await bridge.drain()
                if context.session_id:
                    await session_recorder.end_session(context.session_id)
                break

    except WebSocketDisconnect:
        await bridge.drain()
        if context.session_id:
            await session_recorder.end_session(context.session_id)

    return bridge


@router.websocket("/ws/twilio")
async def twilio_media_stream(websocket: WebSocket) -> None:
    await handle_twilio_media_stream(websocket)
