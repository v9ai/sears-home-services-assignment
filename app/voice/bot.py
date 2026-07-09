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

from fastapi import WebSocket
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from app.agent.prompts import GREETING, build_system_prompt
from app.voice.processors import (
    SafetyGateProcessor,
    SpokenTextSanitizer,
    SystemPromptRefreshProcessor,
)
from app.voice.session import VoiceSession
from app.voice.tools import build_tools

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


def build_pipeline_task(
    transport: FastAPIWebsocketTransport, session: VoiceSession
) -> PipelineTask:
    """Assemble the full pipeline + task for one call. Split out so it is unit-importable
    (the offline pipeline-build verification constructs this with a fake transport)."""
    stt = _build_stt()
    llm = _build_llm()
    tts = _build_tts()

    # Tools: the ported LlamaIndex tools as Pipecat function schemas + handlers.
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
    aggregators = LLMContextAggregatorPair(context)

    safety_gate = SafetyGateProcessor(session, context)
    prompt_refresh = SystemPromptRefreshProcessor(session, context)
    sanitizer = SpokenTextSanitizer()

    pipeline = Pipeline(
        [
            transport.input(),
            VADProcessor(vad_analyzer=SileroVADAnalyzer()),  # Silero VAD (barge-in/turns)
            stt,
            safety_gate,  # pre-LLM hazard interrupt (app/agent/safety.py)
            prompt_refresh,  # re-inject live CaseFile into the system prompt each turn
            aggregators.user(),
            llm,  # runs the function-calling loop over the ported tools
            sanitizer,  # strip markdown/URLs before speech
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=TWILIO_SAMPLE_RATE,
            audio_out_sample_rate=TWILIO_SAMPLE_RATE,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
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

    return task


async def run_bot(websocket: WebSocket, stream_sid: str, call_sid: str | None) -> None:
    """Entry point invoked by the Twilio Media Streams WebSocket route (`app/voice/routes.py`).

    `stream_sid`/`call_sid` come from Twilio's `start` message. The serializer needs the
    account SID + auth token to auto-hang-up the PSTN leg when the pipeline ends.
    """
    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=os.environ.get("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
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
    task = build_pipeline_task(transport, session)

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
