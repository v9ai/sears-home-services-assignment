"""Pipeline assembly + swappable-provider selection for `app/voice/bot.py`.

`build_pipeline_task` is the split-out seam (`bot.py`) so the whole pipeline can be built
offline with a fake transport — no sockets, no live services. The provider factories are
env-driven; these tests pin the default selections and the swap paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("pipecat.pipeline.task")


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-secret")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test-not-a-secret")
    # default provider selection unless a test overrides
    for var in ("STT_PROVIDER", "LLM_PROVIDER", "TTS_PROVIDER", "VOICE_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)


def _fake_transport() -> MagicMock:
    transport = MagicMock()
    transport.input.return_value = MagicMock(name="input")
    transport.output.return_value = MagicMock(name="output")
    transport.event_handler.return_value = lambda fn: fn  # decorator passthrough
    return transport


def test_build_pipeline_task_constructs_with_fake_transport():
    from pipecat.pipeline.task import PipelineTask

    from app.voice.bot import build_pipeline_task
    from app.voice.session import VoiceSession

    task = build_pipeline_task(_fake_transport(), VoiceSession.for_call("CA_test"))
    assert isinstance(task, PipelineTask)


def test_default_providers(monkeypatch):
    from pipecat.services.deepgram.stt import DeepgramSTTService
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.services.openai.tts import OpenAITTSService

    from app.voice import bot

    assert isinstance(bot._build_stt(), DeepgramSTTService)  # task default
    assert isinstance(bot._build_llm(), OpenAILLMService)  # gpt-4o default (confirmed choice)
    assert isinstance(bot._build_tts(), OpenAITTSService)  # gpt-4o-mini-tts default


def test_stt_swap_to_openai(monkeypatch):
    from pipecat.services.openai.stt import OpenAISTTService

    from app.voice import bot

    monkeypatch.setenv("STT_PROVIDER", "openai")
    assert isinstance(bot._build_stt(), OpenAISTTService)


def test_llm_swap_to_deepseek(monkeypatch):
    from pipecat.services.deepseek.llm import DeepSeekLLMService

    from app.voice import bot

    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test-not-a-secret")
    assert isinstance(bot._build_llm(), DeepSeekLLMService)


def test_tts_swap_to_deepgram(monkeypatch):
    from pipecat.services.deepgram.tts import DeepgramTTSService

    from app.voice import bot

    monkeypatch.setenv("TTS_PROVIDER", "deepgram")
    assert isinstance(bot._build_tts(), DeepgramTTSService)
