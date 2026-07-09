"""The Pipecat voice pipeline for one Twilio call — the port's entrypoint.

`run_bot(websocket, stream_sid, call_sid)` builds and runs the whole pipeline:

    transport.input()  →  VAD  →  STT  →  SafetyGate  →  SystemPromptRefresh
        →  context.user()  →  LLM (+ ported tools)  →  Sanitizer  →  TTS
        →  transport.output()  →  context.assistant()

The LLM here runs the function-calling loop that the LlamaIndex `FunctionAgent` used to
run; the tools it calls are the SAME `app.tools.*` functions (bridged in
`app/voice/tools.py`), the system prompt is the SAME `build_system_prompt`
(`app/agent/prompts.py`), and the safety gate is the SAME `detect_safety_trigger`
(`app/agent/safety.py`). Providers are swappable via env; defaults are Deepgram STT,
OpenAI gpt-4o LLM, and OpenAI gpt-4o-mini-tts TTS (see README).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from fastapi import WebSocket
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from app.agent.prompts import GREETING, build_system_prompt
from app.obs import log_event
from app.voice.metrics import VoiceMetricsObserver
from app.voice.processors import (
    SafetyGateProcessor,
    SpokenTextSanitizer,
    SystemPromptRefreshProcessor,
)
from app.voice.serializer import SafeTwilioFrameSerializer
from app.voice.session import VoiceSession
from app.voice.tools import build_tools

if TYPE_CHECKING:
    # Deferred: app.phone.latency is a submodule of app.phone, whose __init__ imports
    # app.voice.routes -> app.voice.bot — importing it at module level here would be
    # circular whenever app.voice.bot is imported directly (e.g. from tests) before
    # app.phone has been loaded via some other path. build_pipeline_task() below does
    # the real (deferred, runtime) import right where LatencyRecorder is constructed.
    from app.phone.latency import LatencyRecorder

logger = logging.getLogger("app.voice.bot")

# Twilio Media Streams is 8 kHz mono µ-law; run the pipeline at 8 kHz end-to-end to avoid
# needless resampling (the serializer handles the µ-law <-> PCM conversion).
TWILIO_SAMPLE_RATE = 8000


# --- swappable provider factories (keys from env) ------------------------------------
def _build_stt():
    provider = os.environ.get("STT_PROVIDER", "deepgram").strip().lower()
    if provider == "openai":
        from pipecat.services.openai.stt import OpenAISTTService

        return OpenAISTTService(
            api_key=os.environ["OPENAI_API_KEY"],
            model=os.environ.get("OPENAI_STT_MODEL", "gpt-4o-transcribe"),
        )
    # default: Deepgram streaming STT (task default)
    from pipecat.services.deepgram.stt import DeepgramSTTService

    return DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])


def _build_llm():
    # Default OpenAI gpt-4o (the existing LLM_PROVIDER=openai path, chosen for reliable
    # real-time tool-calling); LLM_PROVIDER=deepseek matches the LlamaIndex agent's
    # default deepseek-chat for parity.
    provider = os.environ.get("LLM_PROVIDER", "openai").strip().lower()
    if provider == "deepseek":
        from pipecat.services.deepseek.llm import DeepSeekLLMService

        return DeepSeekLLMService(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        )
    from pipecat.services.openai.llm import OpenAILLMService

    # Dedicated VOICE_LLM_MODEL (default gpt-4o, the confirmed choice for the voice loop) so
    # the pipeline LLM is decoupled from the shared OPENAI_LLM_MODEL the LlamaIndex agent uses.
    # LATENCY NOTE (specs/features/2026-07-08-latency-engineering P2-2): gpt-4o measured
    # ~6.16 s to first sentence, above the p50 ≤ 2.5 s / p95 ≤ 4 s end-of-speech→first-audio
    # budget; `gpt-4.1-mini` won that sweep (~4.29 s, tools-correct). Kept on gpt-4o here as a
    # deliberate quality choice — set VOICE_LLM_MODEL=gpt-4.1-mini to prioritize first-audio
    # latency.
    return OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(model=os.environ.get("VOICE_LLM_MODEL", "gpt-4o")),
    )


def _build_tts():
    provider = os.environ.get("TTS_PROVIDER", "openai").strip().lower()
    if provider == "cartesia":
        from pipecat.services.cartesia.tts import CartesiaTTSService

        return CartesiaTTSService(
            api_key=os.environ["CARTESIA_API_KEY"],
            voice_id=os.environ["CARTESIA_VOICE_ID"],
        )
    if provider == "deepgram":
        from pipecat.services.deepgram.tts import DeepgramTTSService

        return DeepgramTTSService(
            api_key=os.environ["DEEPGRAM_API_KEY"],
            voice=os.environ.get("DEEPGRAM_AURA_VOICE", "aura-2-thalia-en"),
        )
    # default: OpenAI gpt-4o-mini-tts (reuse the app's existing TTS provider/key)
    from pipecat.services.openai.tts import OpenAITTSService

    return OpenAITTSService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAITTSService.Settings(
            model=os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
            voice=os.environ.get("OPENAI_TTS_VOICE", "alloy"),
        ),
    )


def _build_conversation_pipeline(
    session: VoiceSession,
    stt: STTService,
    llm: LLMService,
    tts: TTSService,
    *,
    user_turn_strategies: UserTurnStrategies | None = None,
) -> tuple[Pipeline, LLMContext, SystemPromptRefreshProcessor]:
    """STT -> safety -> prompt refresh -> user agg -> LLM -> sanitizer -> TTS -> assistant
    agg, without VAD or transport stages, so this sub-pipeline can be driven directly
    through `pipecat.tests.utils.run_test` with injected fake services (see
    `tests/voice/test_voice_latency_e2e.py`).

    `user_turn_strategies` is a test-only override — production (`build_pipeline_task`)
    never passes it, so `LLMContextAggregatorPair` keeps Pipecat's own default
    turn-detection strategies (VAD + transcription start, smart-turn stop).
    """
    tools_schema, handlers = build_tools(session)
    for name, handler in handlers.items():
        llm.register_function(name, handler)

    # LLM context seeded with the case-file-current system prompt (refreshed each turn by
    # SystemPromptRefreshProcessor). This context + its aggregators are the Pipecat
    # equivalent of the LlamaIndex ChatMemoryBuffer (verbatim history) plus the per-turn
    # CaseFile-in-prompt (structured never-re-ask memory).
    context = LLMContext(
        messages=[{"role": "system", "content": build_system_prompt(session.case_file)}],
        tools=tools_schema,
    )
    user_params = (
        LLMUserAggregatorParams(user_turn_strategies=user_turn_strategies)
        if user_turn_strategies is not None
        else None
    )
    aggregators = LLMContextAggregatorPair(context, user_params=user_params)

    safety_gate = SafetyGateProcessor(session, context)
    prompt_refresh = SystemPromptRefreshProcessor(session, context)
    sanitizer = SpokenTextSanitizer()

    pipeline = Pipeline(
        [
            stt,
            safety_gate,  # pre-LLM hazard interrupt (app/agent/safety.py)
            prompt_refresh,  # re-inject live CaseFile into the system prompt each turn
            aggregators.user(),
            llm,  # runs the function-calling loop over the ported tools
            sanitizer,  # strip markdown/URLs before speech
            tts,
            aggregators.assistant(),
        ]
    )
    return pipeline, context, prompt_refresh


def build_pipeline_task(
    transport: FastAPIWebsocketTransport,
    session: VoiceSession,
    *,
    stt: STTService | None = None,
    llm: LLMService | None = None,
    tts: TTSService | None = None,
) -> tuple[PipelineTask, LatencyRecorder]:
    """Assemble the full pipeline + task for one call. Split out so it is unit-importable
    (the offline pipeline-build verification constructs this with a fake transport).

    `stt`/`llm`/`tts` are optional injection points for tests (fall back to the real
    provider factories below) — `run_bot`'s production call never passes them, so
    production behavior is unchanged."""
    from app.phone.latency import LatencyRecorder  # deferred: see the TYPE_CHECKING note above

    stt = stt or _build_stt()
    llm = llm or _build_llm()
    tts = tts or _build_tts()

    conversation, context, prompt_refresh = _build_conversation_pipeline(session, stt, llm, tts)

    pipeline = Pipeline(
        [
            transport.input(),
            VADProcessor(vad_analyzer=SileroVADAnalyzer()),  # Silero VAD (barge-in/turns)
            conversation,
            transport.output(),
        ]
    )

    recorder = LatencyRecorder()
    observer = VoiceMetricsObserver(recorder)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=TWILIO_SAMPLE_RATE,
            audio_out_sample_rate=TWILIO_SAMPLE_RATE,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[observer],
    )

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client) -> None:  # noqa: ANN001
        # Speak the fixed greeting (a constant, like the original GREETING) without an LLM
        # round-trip, and seed it into history so the model knows it already greeted.
        logger.info("voice_call_connected call=%s session=%s", session.call_sid, session.session_id)
        prompt_refresh.refresh()
        context.add_message({"role": "assistant", "content": GREETING})
        await task.queue_frames([TTSSpeakFrame(GREETING)])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport, _client) -> None:  # noqa: ANN001
        logger.info("voice_call_ended call=%s session=%s", session.call_sid, session.session_id)
        await task.cancel()

    return task, recorder


async def run_bot(websocket: WebSocket, stream_sid: str, call_sid: str | None) -> None:
    """Entry point invoked by the Twilio Media Streams WebSocket route (`app/voice/routes.py`).

    `stream_sid`/`call_sid` come from Twilio's `start` message. The serializer needs the
    account SID + auth token to auto-hang-up the PSTN leg when the pipeline ends.
    """
    # The serializer needs the account SID + auth token to auto-hang-up the PSTN leg when the
    # pipeline ends. With either unset it silently skips the hangup (a dangling call leg); make
    # that degraded mode observable instead of failing silently.
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not account_sid or not auth_token:
        log_event(
            logger,
            "twilio.serializer.autohangup_disabled",
            reason="missing_twilio_credentials",
        )
    serializer = SafeTwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=account_sid,
        auth_token=auth_token,
    )
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,  # raw µ-law for telephony
            serializer=serializer,
        ),
    )

    session = VoiceSession.for_call(call_sid)
    task, _latency_recorder = build_pipeline_task(transport, session)

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    except Exception as exc:  # teardown safety net beyond on_client_disconnected
        # Any unexpected pipeline error must still tear down the call leg; log a sanitized
        # event (never the payload) and cancel so we don't leak a running task.
        log_event(logger, "twilio.pipeline.error", error=type(exc).__name__)
        await task.cancel()
