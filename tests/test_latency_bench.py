"""Offline tests for `scripts/latency_bench.py`.

None of these touch the network -- the key-gated skip path never calls a bench
function, and the schema/table tests exercise pure functions with synthetic sample
lists (the harness's own "budget-table math" and "skip-loud without keys" self-tests).
"""

from __future__ import annotations

import json

import pytest

from scripts import latency_bench


def test_missing_keys_reports_both_llm_and_openai_when_unset(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    missing = latency_bench.missing_keys()

    assert missing == ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"]


def test_missing_keys_checks_openai_provider_key_when_selected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    missing = latency_bench.missing_keys()

    assert missing == ["OPENAI_API_KEY"]


def test_missing_keys_empty_when_both_present(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")

    assert latency_bench.missing_keys() == []


def test_main_skips_without_calling_network_bench_when_keys_absent(monkeypatch, capsys):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    async def _boom():
        raise AssertionError("network-touching bench path must not run when keys are missing")

    monkeypatch.setattr(latency_bench, "_run_live", _boom)

    exit_code = latency_bench.main()

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "SKIP" in out


def test_build_report_schema_shape():
    micro = {
        "eos_to_stt_ms": [500.0, 550.0, 600.0, 620.0, 650.0],
        "llm_ttft_ms": [800.0, 850.0, 900.0, 950.0, 1000.0],
        "tts_first_byte_ms": [200.0, 220.0, 240.0, 260.0, 280.0],
    }
    e2e_web = [
        {"submit_to_first_audio_ms": 1800.0},
        {"submit_to_first_audio_ms": 2100.0},
    ]
    e2e_phone = [
        {"eos_to_first_audio_ms": 2000.0},
        {"eos_to_first_audio_ms": 2200.0},
    ]

    report = latency_bench.build_report(
        micro, e2e_web, e2e_phone, llm_provider="deepseek", timestamp="20260708T000000Z"
    )

    assert report["timestamp"] == "20260708T000000Z"
    assert report["llm_provider"] == "deepseek"
    assert set(report["micro_benchmarks"]) == {"eos_to_stt_ms", "llm_ttft_ms", "tts_first_byte_ms"}
    for stage in report["micro_benchmarks"].values():
        assert set(stage) == {"samples_ms", "p50", "p95", "budget_ms", "pass"}
    assert report["end_to_end"]["web"]["pass"] is True
    assert report["end_to_end"]["phone"]["pass"] is True
    assert report["overall_pass"] is True
    assert "note" in report["end_to_end"]["phone"]


def test_build_report_fails_when_a_stage_is_over_budget():
    micro = {
        "eos_to_stt_ms": [500.0] * 5,
        "llm_ttft_ms": [5000.0] * 5,  # way over the 1200ms budget
        "tts_first_byte_ms": [200.0] * 5,
    }
    report = latency_bench.build_report(
        micro, [], [], llm_provider="deepseek", timestamp="20260708T000000Z"
    )

    assert report["micro_benchmarks"]["llm_ttft_ms"]["pass"] is False
    assert report["overall_pass"] is False


def test_e2e_pass_requires_non_empty_records():
    # No scenarios driven -> no data is a FAIL, not a silent pass.
    report = latency_bench.build_report(
        {"eos_to_stt_ms": [1], "llm_ttft_ms": [1], "tts_first_byte_ms": [1]},
        [],
        [],
        llm_provider="deepseek",
        timestamp="20260708T000000Z",
    )
    assert report["end_to_end"]["web"]["pass"] is False
    assert report["end_to_end"]["phone"]["pass"] is False


def test_web_e2e_gated_by_web_budget():
    """The web channel has its own, stricter budget (2000/3500 ms vs phone 2500/4000 —
    specs/latency/budgets.md): a 2200 ms web p50 must FAIL web while the identical
    phone numbers PASS. Pre-fix, both channels were gated by the phone budget."""
    micro = {
        "eos_to_stt_ms": [1.0],
        "llm_ttft_ms": [1.0],
        "tts_first_byte_ms": [1.0],
    }
    e2e_web = [{"submit_to_first_audio_ms": 2200.0}] * 5
    e2e_phone = [{"eos_to_first_audio_ms": 2200.0}] * 5

    report = latency_bench.build_report(
        micro, e2e_web, e2e_phone, llm_provider="openai", timestamp="20260709T000000Z"
    )

    assert report["end_to_end"]["web"]["pass"] is False
    assert report["end_to_end"]["phone"]["pass"] is True
    assert report["overall_pass"] is False


def test_e2e_summaries_carry_their_own_budgets():
    from app.latency.budgets import PHONE_E2E, WEB_E2E

    report = latency_bench.build_report(
        {"eos_to_stt_ms": [1.0], "llm_ttft_ms": [1.0], "tts_first_byte_ms": [1.0]},
        [{"submit_to_first_audio_ms": 100.0}],
        [{"eos_to_first_audio_ms": 100.0}],
        llm_provider="openai",
        timestamp="ts",
    )

    web, phone = report["end_to_end"]["web"], report["end_to_end"]["phone"]
    assert (web["budget_p50_ms"], web["budget_p95_ms"]) == (WEB_E2E.p50_ms, WEB_E2E.p95_ms)
    assert (phone["budget_p50_ms"], phone["budget_p95_ms"]) == (PHONE_E2E.p50_ms, PHONE_E2E.p95_ms)


def test_report_budgets_sourced_from_module():
    from app.latency import budgets

    report = latency_bench.build_report(
        {"eos_to_stt_ms": [1.0], "llm_ttft_ms": [1.0], "tts_first_byte_ms": [1.0]},
        [],
        [],
        llm_provider="openai",
        timestamp="ts",
    )

    assert report["budgets_ms"] == {
        **budgets.MICRO_BUDGETS_MS,
        "web_e2e_p50_ms": budgets.WEB_E2E.p50_ms,
        "web_e2e_p95_ms": budgets.WEB_E2E.p95_ms,
        "phone_e2e_p50_ms": budgets.PHONE_E2E.p50_ms,
        "phone_e2e_p95_ms": budgets.PHONE_E2E.p95_ms,
    }


def test_report_schema_version():
    report = latency_bench.build_report(
        {"eos_to_stt_ms": [1.0], "llm_ttft_ms": [1.0], "tts_first_byte_ms": [1.0]},
        [],
        [],
        llm_provider="openai",
        timestamp="ts",
    )
    assert report["schema_version"] == 2


def test_stage_result_empty_samples_fail():
    # No data is a FAIL at stage level too, matching the e2e no-data-is-FAIL behavior.
    result = latency_bench._stage_result([], 900)
    assert result["pass"] is False


def test_write_report_writes_valid_json(tmp_path):
    report = latency_bench.build_report(
        {"eos_to_stt_ms": [1], "llm_ttft_ms": [1], "tts_first_byte_ms": [1]},
        [{"submit_to_first_audio_ms": 100.0}],
        [{"eos_to_first_audio_ms": 100.0}],
        llm_provider="deepseek",
        timestamp="20260708T000000Z",
    )

    path = latency_bench.write_report(report, out_dir=tmp_path)

    assert path == tmp_path / "20260708T000000Z.json"
    assert json.loads(path.read_text())["timestamp"] == "20260708T000000Z"


def test_render_table_marks_over_budget_stage_as_fail():
    report = latency_bench.build_report(
        {
            "eos_to_stt_ms": [500.0] * 5,
            "llm_ttft_ms": [5000.0] * 5,
            "tts_first_byte_ms": [200.0] * 5,
        },
        [{"submit_to_first_audio_ms": 1000.0}],
        [{"eos_to_first_audio_ms": 1000.0}],
        llm_provider="deepseek",
        timestamp="20260708T000000Z",
    )

    table = latency_bench.render_table(report)

    assert "llm_ttft_ms" in table
    lines = {line.split()[0]: line for line in table.splitlines() if line.startswith("llm_ttft_ms")}
    assert "FAIL" in lines["llm_ttft_ms"]
    assert "overall: FAIL" in table


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_main_exit_code_reflects_overall_pass_when_gate_hard(monkeypatch, value):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.setenv("LATENCY_GATE_HARD", value)

    async def _fake_run_live():
        return latency_bench.build_report(
            {"eos_to_stt_ms": [5000.0]}, [], [], llm_provider="deepseek", timestamp="ts"
        )

    monkeypatch.setattr(latency_bench, "_run_live", _fake_run_live)
    monkeypatch.setattr(latency_bench, "write_report", lambda report, out_dir=None: "unused")

    assert latency_bench.main() == 1


def test_main_exit_code_zero_when_gate_advisory(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.delenv("LATENCY_GATE_HARD", raising=False)

    async def _fake_run_live():
        return latency_bench.build_report(
            {"eos_to_stt_ms": [5000.0]}, [], [], llm_provider="deepseek", timestamp="ts"
        )

    monkeypatch.setattr(latency_bench, "_run_live", _fake_run_live)
    monkeypatch.setattr(latency_bench, "write_report", lambda report, out_dir=None: "unused")

    assert latency_bench.main() == 0


# --- bench-fidelity regression tests (runbook §1 RCA, 2026-07-09) --------------------


async def test_bench_tts_ttfb_measures_the_cached_filler_path(monkeypatch):
    """RCA item 1: the tts row must measure the production P0-1 cache path for the
    constant filler, not the raw provider TTFB the caller never hears."""
    calls: dict = {}

    async def fake_prewarm(formats=("pcm",)):
        calls["prewarm_formats"] = formats

    async def fake_synth_cached(text, **kwargs):
        calls.setdefault("texts", []).append(text)
        yield b"\x00"

    monkeypatch.setattr("app.agent.tts_cache.prewarm", fake_prewarm)
    monkeypatch.setattr("app.agent.tts_cache.synthesize_cached", fake_synth_cached)

    samples = await latency_bench.bench_tts_ttfb(n=2)

    from app.agent.fillers import PHONE_TOOL_FILLER

    assert calls["prewarm_formats"] == ("mp3",)
    assert calls["texts"] == [PHONE_TOOL_FILLER] * 2
    assert len(samples) == 2


async def test_transcribe_bounded_survives_a_hung_provider(monkeypatch):
    """RCA item 3: one stalled STT request must not own the whole p95 — bounded with
    one retry, returning (never raising) so the elapsed cap stands as the sample."""
    import asyncio
    import time

    monkeypatch.setattr(latency_bench, "STT_BENCH_TIMEOUT_S", 0.05)

    class HangingTranscriber:
        calls = 0

        async def transcribe(self, pcm, rate):
            type(self).calls += 1
            await asyncio.sleep(10)

    start = time.monotonic()
    await latency_bench._transcribe_bounded(HangingTranscriber(), b"", 8000)
    assert HangingTranscriber.calls == 2  # first attempt + one retry, both bounded
    assert time.monotonic() - start < 1.0


async def test_transcribe_bounded_retry_recovers(monkeypatch):
    import asyncio

    monkeypatch.setattr(latency_bench, "STT_BENCH_TIMEOUT_S", 0.05)

    class FlakyTranscriber:
        calls = 0

        async def transcribe(self, pcm, rate):
            type(self).calls += 1
            if type(self).calls == 1:
                await asyncio.sleep(10)

    await latency_bench._transcribe_bounded(FlakyTranscriber(), b"", 8000)
    assert FlakyTranscriber.calls == 2


def test_main_registers_instrumentation_before_running(monkeypatch):
    """P2-1: the bench process must register the llama-index handlers itself or every
    record reports llm_calls=0 and the round-trip count is invisible in the traces."""
    calls: list[str] = []

    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.delenv("LATENCY_GATE_HARD", raising=False)

    import app.agent.instrumentation as instrumentation

    monkeypatch.setattr(
        instrumentation, "register_instrumentation", lambda: calls.append("registered")
    )

    async def _fake_run_live():
        return latency_bench.build_report(
            {"eos_to_stt_ms": [1.0]}, [], [], llm_provider="deepseek", timestamp="ts"
        )

    monkeypatch.setattr(latency_bench, "_run_live", _fake_run_live)
    monkeypatch.setattr(latency_bench, "write_report", lambda report, out_dir=None: "unused")

    assert latency_bench.main() == 0
    assert calls == ["registered"]
