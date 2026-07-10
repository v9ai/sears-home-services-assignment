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
OpenAI gpt-4.1-mini LLM, and Cartesia sonic-3.5 TTS (see README).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
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
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
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
    FillerProcessor,
    SafetyGateProcessor,
    SpokenTextSanitizer,
    SystemPromptRefreshProcessor,
)
from app.voice.recording import (
    call_recording_path,
    ensure_voice_session_row,
    persist_voice_session,
    recording_enabled,
    write_stereo_wav,
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

# Twilio Media Streams is 8 kHz mono µ-law; run the transport at 8 kHz (the serializer
# handles the µ-law <-> PCM conversion).
TWILIO_SAMPLE_RATE = 8000

# OpenAI's TTS API only ever returns 24 kHz PCM (there is no rate parameter on the request),
# so the service must emit frames LABELLED 24 kHz and let the output transport resample them
# down to TWILIO_SAMPLE_RATE. If it instead inherits the transport's 8 kHz, pipecat tags the
# 24 kHz audio as 8 kHz: no resample happens and the µ-law encoder ships raw 24 kHz samples,
# which Twilio plays back ~3x too slow and an octave-plus low — i.e. garbled speech.
OPENAI_TTS_SAMPLE_RATE = 24000

# Words a caller must get transcribed before they can interrupt the speaking bot —
# the barge-in echo guard (see _build_user_turn_strategies). Env: VOICE_BARGEIN_MIN_WORDS.
VOICE_BARGEIN_MIN_WORDS_DEFAULT = 3


# --- swappable provider factories (keys from env) ------------------------------------
def _build_stt():
    # Default Deepgram streaming STT: it transcribes incrementally and finalizes at
    # end-of-speech, so the caller isn't stuck in silence while a full-utterance buffer is
    # transcribed — the key first-audio-latency win over OpenAI's buffered gpt-4o-transcribe.
    # STT_PROVIDER=openai swaps back to gpt-4o-transcribe (stronger on error codes/model #s).
    provider = os.environ.get("STT_PROVIDER", "deepgram").strip().lower()
    if provider == "openai":
        from pipecat.services.openai.stt import OpenAISTTService

        # Language hint: pins STT to English for this US home-services line, curbing the
        # Whisper-family habit of hallucinating a foreign language on short/near-silent clips
        # (pre-port fix in app/phone/stt.py::OpenAITranscriber that the Pipecat port dropped —
        # observed live 2026-07-09 as an Arabic turn). Any ISO-639-1 code retargets the caller
        # base; OPENAI_STT_LANGUAGE="" omits the field, deferring to pipecat's own service
        # default (also "en" today — there is no true auto-detect through this service).
        settings_kwargs: dict = {"model": os.environ.get("OPENAI_STT_MODEL", "gpt-4o-transcribe")}
        language = os.environ.get("OPENAI_STT_LANGUAGE", "en").strip()
        if language:
            settings_kwargs["language"] = language
        return OpenAISTTService(
            api_key=os.environ["OPENAI_API_KEY"],
            settings=OpenAISTTService.Settings(**settings_kwargs),
        )
    if provider == "cartesia":
        from pipecat.services.cartesia.stt import CartesiaSTTService

        # Same English pin as the OpenAI branch above (ink-whisper is Whisper-family, so
        # it shares the foreign-language hallucination habit). "" omits the field.
        cartesia_kwargs: dict = {"model": os.environ.get("CARTESIA_STT_MODEL", "ink-whisper")}
        cartesia_language = os.environ.get("CARTESIA_STT_LANGUAGE", "en").strip()
        if cartesia_language:
            cartesia_kwargs["language"] = cartesia_language
        return CartesiaSTTService(
            api_key=os.environ["CARTESIA_API_KEY"],
            settings=CartesiaSTTService.Settings(**cartesia_kwargs),
        )
    # default: Deepgram streaming STT (task default)
    from pipecat.services.deepgram.stt import DeepgramSTTService

    # English pin for the default path too (Deepgram takes BCP-47, hence en-US) — the
    # agent is English-only by design (specs/constitution/mission.md non-goals).
    # DEEPGRAM_STT_LANGUAGE="" omits the field, restoring Deepgram's own default.
    deepgram_kwargs: dict = {}
    deepgram_language = os.environ.get("DEEPGRAM_STT_LANGUAGE", "en-US").strip()
    if deepgram_language:
        deepgram_kwargs["language"] = deepgram_language
    return DeepgramSTTService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        settings=DeepgramSTTService.Settings(**deepgram_kwargs),
    )


def _build_llm():
    # Default OpenAI gpt-4o (the existing LLM_PROVIDER=openai path, chosen for reliable
    # real-time tool-calling); LLM_PROVIDER=deepseek matches the LlamaIndex agent's
    # default deepseek-chat for parity.
    provider = os.environ.get("LLM_PROVIDER", "openai").strip().lower()
    if provider == "deepseek":
        from pipecat.services.deepseek.llm import DeepSeekLLMService

        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        if model.startswith("deepseek-reasoner"):
            # Fail fast at build time instead of confusingly mid-call: reasoner has no
            # function calling, which the voice tool loop requires (.env.example:6).
            raise ValueError(
                "deepseek-reasoner is not supported: it has no function calling, "
                "which the voice tool loop requires. Use deepseek-chat."
            )
        return DeepSeekLLMService(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            settings=DeepSeekLLMService.Settings(model=model),
        )
    from pipecat.services.openai.llm import OpenAILLMService

    # Dedicated VOICE_LLM_MODEL (default gpt-4.1-mini) so the pipeline LLM is decoupled
    # from the shared OPENAI_LLM_MODEL the LlamaIndex agent uses.
    # LATENCY NOTE (specs/features/2026-07-08-latency-engineering P2-2): gpt-4.1-mini won
    # the first-sentence sweep (~4.29 s vs gpt-4o's ~6.16 s, tools-correct 3/3) and is the
    # default as of loop-v2 i10 (f5 model-pin — user-approved 2026-07-09 conditional on
    # evals green; .env has pinned this value live since 2026-07-10). Set
    # VOICE_LLM_MODEL=gpt-4o to trade first-audio latency back for the larger model.
    return OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(model=os.environ.get("VOICE_LLM_MODEL", "gpt-4.1-mini")),
    )


def _build_tts():
    # Default Cartesia (sonic-3.5, streamed over a websocket): the lowest first-audio-byte
    # latency of the three TTS options, and — unlike OpenAI's TTS below — it accepts an
    # explicit sample rate in its handshake and self-adapts to the pipeline's rate, so no
    # sample_rate needs to be pinned here (see OPENAI_TTS_SAMPLE_RATE note for the contrast).
    # TTS_PROVIDER=openai / deepgram swap back to the other two branches below.
    provider = os.environ.get("TTS_PROVIDER", "cartesia").strip().lower()
    if provider == "openai":
        from pipecat.services.openai.tts import OpenAITTSService

        return OpenAITTSService(
            api_key=os.environ["OPENAI_API_KEY"],
            # Native 24 kHz; the output transport resamples to TWILIO_SAMPLE_RATE (see the
            # OPENAI_TTS_SAMPLE_RATE note above). Without this the call audio is garbled.
            sample_rate=OPENAI_TTS_SAMPLE_RATE,
            settings=OpenAITTSService.Settings(
                model=os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
                voice=os.environ.get("OPENAI_TTS_VOICE", "alloy"),
            ),
        )
    if provider == "deepgram":
        from pipecat.services.deepgram.tts import DeepgramTTSService

        return DeepgramTTSService(
            api_key=os.environ["DEEPGRAM_API_KEY"],
            settings=DeepgramTTSService.Settings(
                voice=os.environ.get("DEEPGRAM_AURA_VOICE", "aura-2-thalia-en"),
            ),
        )
    # default: Cartesia (sample_rate left unset — see comment above)
    from pipecat.services.cartesia.tts import CartesiaTTSService

    return CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        settings=CartesiaTTSService.Settings(
            voice=os.environ["CARTESIA_VOICE_ID"],
            model=os.environ.get("CARTESIA_TTS_MODEL", "sonic-3.5"),
            # English-only line: keeps sonic from mirroring a non-English LLM slip.
            language=os.environ.get("CARTESIA_TTS_LANGUAGE", "en"),
        ),
    )


def _build_vad_analyzer() -> SileroVADAnalyzer:
    # Silero VAD. Its stop-hangover — the silence the caller must leave after they finish
    # speaking before the turn is considered over — is pure dead air that elapses BEFORE STT
    # even finalizes, so it directly taxes the "delay after I respond" the caller feels.
    # Pipecat's default is ~0.8 s; VAD_STOP_SECS lowers it (default + safe floor recorded in
    # app/latency/budgets.py). Below the floor callers get cut off mid-utterance (false
    # end-of-turn) — an explicit override is honored but logged, never clamped.
    from pipecat.audio.vad.vad_analyzer import VADParams

    from app.latency.budgets import VAD_STOP_SECS_DEFAULT, VAD_STOP_SECS_MIN_SAFE

    stop_secs = float(os.environ.get("VAD_STOP_SECS", str(VAD_STOP_SECS_DEFAULT)))
    if stop_secs < VAD_STOP_SECS_MIN_SAFE:
        log_event(
            logger,
            "voice.vad.stop_secs_below_safe_floor",
            stop_secs=stop_secs,
            min_safe=VAD_STOP_SECS_MIN_SAFE,
        )
    return SileroVADAnalyzer(params=VADParams(stop_secs=stop_secs))


def _build_user_turn_strategies() -> UserTurnStrategies | None:
    """Barge-in guard for the AEC-less PSTN leg (docs/local-twilio-run.md "Stuttering
    during the reply").

    A phone call has no acoustic echo cancellation, so while the bot speaks its own TTS
    returns on the inbound leg. Pipecat's default turn-start strategies interrupt on a
    single raw VAD frame (or any 1-word transcription), so that echo fires interruption
    → Twilio ``clear`` → the reply is flushed and restarts → the reply is chopped into
    fragments (the stuttering incident originally fixed by the pre-port
    ``BargeInDetector``, lost in the Pipecat port).

    ``MinWordsUserTurnStartStrategy`` is the Pipecat-native equivalent: while the bot is
    speaking a user turn (and its interruption) requires ``min_words`` transcribed words
    — echo blips and 1–2-word STT hallucinations can't interrupt — while a single word
    still opens the turn when the bot is silent, so normal turn-taking is unchanged.
    ``VOICE_BARGEIN_MIN_WORDS=0`` disables the guard (Pipecat defaults), the explicit
    rollback knob.
    """
    from pipecat.turns.user_start.min_words_user_turn_start_strategy import (
        MinWordsUserTurnStartStrategy,
    )

    default = str(VOICE_BARGEIN_MIN_WORDS_DEFAULT)
    min_words = int(os.environ.get("VOICE_BARGEIN_MIN_WORDS", default))
    if min_words <= 0:
        log_event(logger, "voice.bargein.guard_disabled", min_words=min_words)
        return None
    return UserTurnStrategies(
        start=[MinWordsUserTurnStartStrategy(min_words=min_words, use_interim=True)]
    )


def _build_conversation_pipeline(
    session: VoiceSession,
    stt: STTService,
    llm: LLMService,
    tts: TTSService,
    *,
    user_turn_strategies: UserTurnStrategies | None = None,
) -> tuple[Pipeline, LLMContext, SystemPromptRefreshProcessor]:
    """STT -> safety -> prompt refresh -> user agg -> LLM -> filler -> sanitizer -> TTS ->
    assistant agg, without VAD or transport stages, so this sub-pipeline can be driven directly
    through `pipecat.tests.utils.run_test` with injected fake services (see
    `tests/voice/test_voice_latency_e2e.py`).

    `user_turn_strategies` is a test-only override — production (`build_pipeline_task`)
    never passes it, so the pair uses `_build_user_turn_strategies()`: min-words turn
    start (the PSTN barge-in echo guard) + Pipecat's default smart-turn stop.
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
    strategies = (
        user_turn_strategies if user_turn_strategies is not None else _build_user_turn_strategies()
    )
    user_params = (
        LLMUserAggregatorParams(user_turn_strategies=strategies) if strategies is not None else None
    )
    aggregators = LLMContextAggregatorPair(context, user_params=user_params)

    safety_gate = SafetyGateProcessor(session, context)
    prompt_refresh = SystemPromptRefreshProcessor(session, context)
    filler = FillerProcessor()  # env-gated (FILLER_ENABLED); a no-op stage when off
    sanitizer = SpokenTextSanitizer()

    pipeline = Pipeline(
        [
            stt,
            safety_gate,  # pre-LLM hazard interrupt (app/agent/safety.py)
            prompt_refresh,  # re-inject live CaseFile into the system prompt each turn
            aggregators.user(),
            llm,  # runs the function-calling loop over the ported tools
            filler,  # dead-air bridge past FILLER_DELAY_MS (perceived first-audio)
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

    # Full-call recorder (caller = left, bot = right). Placed AFTER transport.output() so it sees
    # both the caller's input audio and the bot's spoken output; writes one stereo WAV per call.
    # Best-effort and gated by VOICE_RECORDING_ENABLED (see app/voice/recording.py).
    audiobuffer = AudioBufferProcessor(num_channels=2) if recording_enabled() else None

    stages = [
        transport.input(),
        VADProcessor(vad_analyzer=_build_vad_analyzer()),  # Silero VAD (barge-in/turns)
        conversation,
        transport.output(),
    ]
    if audiobuffer is not None:
        stages.append(audiobuffer)
    pipeline = Pipeline(stages)

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

    # Mutable holder for the call's start time, stamped on connect and read on disconnect.
    call_times: dict[str, datetime] = {}

    if audiobuffer is not None:

        @audiobuffer.event_handler("on_audio_data")
        async def _on_audio_data(_buffer, audio, sample_rate, num_channels) -> None:  # noqa: ANN001
            # Fired once when recording stops (buffer_size=0). Best-effort: a write failure must
            # never surface into the call teardown (spec 2026-07-08-call-recording-replay Dec. 5).
            try:
                await asyncio.to_thread(
                    write_stereo_wav,
                    call_recording_path(session.session_id),
                    audio,
                    sample_rate,
                    num_channels,
                )
                log_event(logger, "voice.recording.saved", call=session.call_sid, bytes=len(audio))
            except Exception as exc:
                log_event(logger, "voice.recording.write_failed", error=type(exc).__name__)

    # Held reference so the call-start session-row task isn't GC'd mid-flight
    # (2026-07-09-booking-session-attribution): the `sessions` row must exist before a
    # mid-call booking writes `appointments.session_id`, but must not delay the greeting.
    startup_tasks: list[asyncio.Task] = []

    @transport.event_handler("on_client_connected")
    async def _on_connected(_transport, _client) -> None:  # noqa: ANN001
        # Speak the fixed greeting (a constant, like the original GREETING) without an LLM
        # round-trip, and seed it into history so the model knows it already greeted.
        logger.info("voice_call_connected call=%s session=%s", session.call_sid, session.session_id)
        call_times["started_at"] = datetime.now(UTC)
        startup_tasks.append(asyncio.create_task(ensure_voice_session_row(session)))
        if audiobuffer is not None:
            await audiobuffer.start_recording()
        prompt_refresh.refresh()
        context.add_message({"role": "assistant", "content": GREETING})
        await task.queue_frames([TTSSpeakFrame(GREETING)])

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport, _client) -> None:  # noqa: ANN001
        logger.info("voice_call_ended call=%s session=%s", session.call_sid, session.session_id)
        # Flush the recording (triggers on_audio_data) and persist the sessions row so the call
        # lists/replays in the recordings UI — both best-effort, and always followed by cancel().
        if audiobuffer is not None:
            try:
                await audiobuffer.stop_recording()
            except Exception as exc:
                log_event(logger, "voice.recording.stop_failed", error=type(exc).__name__)
        try:
            await persist_voice_session(
                session,
                context,
                call_times.get("started_at", datetime.now(UTC)),
                datetime.now(UTC),
            )
        except Exception as exc:
            log_event(logger, "voice.recording.persist_failed", error=type(exc).__name__)
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
    task, latency_recorder = build_pipeline_task(transport, session)

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    except Exception as exc:  # teardown safety net beyond on_client_disconnected
        # Any unexpected pipeline error must still tear down the call leg; log a sanitized
        # event (never the payload) and cancel so we don't leak a running task.
        log_event(logger, "twilio.pipeline.error", error=type(exc).__name__)
        await task.cancel()
    finally:
        # Final call story in one line: aggregate media counters from the wire boundary
        # (counts only, never payloads) + per-turn latency percentiles. This is the
        # telephony spec's "final call summary" event.
        log_event(
            logger,
            "twilio.call.summary",
            call=call_sid,
            inbound_frames=serializer.inbound_frames,
            outbound_frames=serializer.outbound_frames,
            malformed_frames=serializer.malformed_frames,
            barge_ins=serializer.bargein_clears,
            turns_measured=len(latency_recorder.samples),
            latency_p50_s=latency_recorder.p50,
            latency_p95_s=latency_recorder.p95,
            within_budget=latency_recorder.within_budget(),
        )
