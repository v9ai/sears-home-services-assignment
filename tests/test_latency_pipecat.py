"""Offline tests for `scripts/latency_pipecat.py` (loop v2 q0-4) — the Pipecat-native
e2e bench driven hermetically with fake LLM/TTS services; no network, no keys.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pipecat_frames = pytest.importorskip("pipecat.frames.frames")

from scripts import latency_bench, latency_pipecat  # noqa: E402
from tests.voice.fakes import FakeLLM, FakeTTS  # noqa: E402


def _scenario(sid: str, caller: str = "my dryer is making a loud noise"):
    return SimpleNamespace(id=sid, turns=[SimpleNamespace(caller=caller)])


@pytest.fixture(autouse=True)
def _short_tail(monkeypatch):
    # The 12s live tail is provider headroom; fakes answer in ms — keep tests fast.
    monkeypatch.setattr(latency_pipecat, "TURN_TAIL_S", 0.5)


async def test_bench_drives_production_pipeline_and_records_sample():
    records = await latency_pipecat.bench_e2e_pipecat(
        [_scenario("s1")],
        1,
        llm=FakeLLM(delay_s=0.05),
        tts=FakeTTS(delay_s=0.05),
    )

    assert len(records) == 1
    rec = records[0]
    assert rec["channel"] == "pipecat"
    assert rec["scenario_id"] == "s1"
    assert rec["turn_index"] == 0
    # eos -> first TTSStartedFrame through the real conversation pipeline: at least
    # the fake LLM+TTS delays, well under the bounded tail.
    assert rec["pipecat_eos_to_first_audio_ms"] is not None
    assert 50 <= rec["pipecat_eos_to_first_audio_ms"] < latency_pipecat.TURN_TAIL_S * 1000


async def test_bench_one_record_per_scenario_capped_at_m():
    scenarios = [_scenario("a"), _scenario("b"), _scenario("c")]

    records = await latency_pipecat.bench_e2e_pipecat(
        scenarios, 2, llm=FakeLLM(delay_s=0.01), tts=FakeTTS(delay_s=0.01)
    )

    assert [r["scenario_id"] for r in records] == ["a", "b"]


def test_needed_keys_for_default_providers(monkeypatch):
    # Defaults: LLM openai + TTS cartesia (app/voice/bot.py factories).
    for key in ("LLM_PROVIDER", "TTS_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    for key in ("OPENAI_API_KEY", "CARTESIA_API_KEY", "CARTESIA_VOICE_ID"):
        monkeypatch.delenv(key, raising=False)

    assert latency_pipecat.needed_keys() == [
        "CARTESIA_API_KEY",
        "CARTESIA_VOICE_ID",
        "OPENAI_API_KEY",
    ]


def test_needed_keys_respects_provider_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("TTS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert latency_pipecat.needed_keys() == ["DEEPSEEK_API_KEY"]


def test_needed_keys_empty_when_all_present(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TTS_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("CARTESIA_API_KEY", "y")
    monkeypatch.setenv("CARTESIA_VOICE_ID", "z")

    assert latency_pipecat.needed_keys() == []


# --- report integration (build_report e2e_pipecat) --------------------------------------


def _micro_ok() -> dict:
    return {"eos_to_stt_ms": [1.0], "llm_ttft_ms": [1.0], "tts_first_byte_ms": [1.0]}


def _pipecat_rec(sid: str, ms: float | None) -> dict:
    return {
        "channel": "pipecat",
        "scenario_id": sid,
        "turn_index": 0,
        "pipecat_eos_to_first_audio_ms": ms,
    }


def test_report_includes_pipecat_section_gated_on_phone_budget():
    report = latency_bench.build_report(
        _micro_ok(),
        [{"submit_to_first_audio_ms": 100.0}],
        [{"eos_to_first_audio_ms": 100.0}],
        llm_provider="openai",
        timestamp="ts",
        e2e_pipecat=[_pipecat_rec("s1", 2000.0), _pipecat_rec("s2", 2400.0)],
    )

    pipecat = report["end_to_end"]["pipecat"]
    assert pipecat["pass"] is True  # p50 2000 <= 3200 phone MEANINGFUL budget (h1 split)
    assert report["budgets_ms"]["pipecat_e2e_p50_ms"] == 3200
    assert report["budgets_ms"]["pipecat_e2e_p95_ms"] == 5100
    assert report["overall_pass"] is True


def test_report_pipecat_over_budget_fails_overall():
    report = latency_bench.build_report(
        _micro_ok(),
        [{"submit_to_first_audio_ms": 100.0}],
        [{"eos_to_first_audio_ms": 100.0}],
        llm_provider="openai",
        timestamp="ts",
        e2e_pipecat=[_pipecat_rec("s1", 9000.0)],
    )

    assert report["end_to_end"]["pipecat"]["pass"] is False
    assert report["overall_pass"] is False


def test_report_pipecat_empty_records_fail_loudly():
    # Missing provider keys produce an empty pipecat record list -> FAIL, never skip.
    report = latency_bench.build_report(
        _micro_ok(),
        [{"submit_to_first_audio_ms": 100.0}],
        [{"eos_to_first_audio_ms": 100.0}],
        llm_provider="openai",
        timestamp="ts",
        e2e_pipecat=[],
    )

    assert report["end_to_end"]["pipecat"]["pass"] is False
    assert report["overall_pass"] is False


def test_report_without_pipecat_keeps_v2_shape():
    report = latency_bench.build_report(
        _micro_ok(),
        [{"submit_to_first_audio_ms": 100.0}],
        [{"eos_to_first_audio_ms": 100.0}],
        llm_provider="openai",
        timestamp="ts",
    )

    assert "pipecat" not in report["end_to_end"]
    assert "pipecat_e2e_p50_ms" not in report["budgets_ms"]


def test_measurement_folds_pipecat_channel_when_present():
    def run(ts: str, pipecat_ms: float) -> dict:
        return latency_bench.build_report(
            _micro_ok(),
            [{"submit_to_first_audio_ms": 100.0}],
            [{"eos_to_first_audio_ms": 100.0}],
            llm_provider="openai",
            timestamp=ts,
            e2e_pipecat=[_pipecat_rec("s1", pipecat_ms)],
        )

    m = latency_bench.build_measurement([run("t1", 2000.0), run("t2", 2600.0), run("t3", 2200.0)])

    assert m["e2e"]["pipecat"]["median_p50"] == 2200.0
    assert m["e2e"]["pipecat"]["pass"] is True


def test_measurement_skips_pipecat_when_absent():
    def run(ts: str) -> dict:
        return latency_bench.build_report(
            _micro_ok(),
            [{"submit_to_first_audio_ms": 100.0}],
            [{"eos_to_first_audio_ms": 100.0}],
            llm_provider="openai",
            timestamp=ts,
        )

    m = latency_bench.build_measurement([run("t1"), run("t2")])

    assert "pipecat" not in m["e2e"]
    assert m["overall_pass"] is True


def test_render_table_shows_pipecat_row():
    report = latency_bench.build_report(
        _micro_ok(),
        [{"submit_to_first_audio_ms": 100.0}],
        [{"eos_to_first_audio_ms": 100.0}],
        llm_provider="openai",
        timestamp="ts",
        e2e_pipecat=[_pipecat_rec("s1", 2000.0)],
    )

    table = latency_bench.render_table(report)

    assert "e2e pipecat" in table
