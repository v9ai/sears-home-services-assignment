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


# --- measurement envelope (loop v2 q0-2) ------------------------------------------------


def _run_report(ts: str, *, llm_p50: float, web_p50: float, phone_p50: float) -> dict:
    """A minimal but schema-faithful single-run report for measurement folding."""
    return latency_bench.build_report(
        {
            "eos_to_stt_ms": [500.0] * 5,
            "llm_ttft_ms": [llm_p50] * 5,
            "tts_first_byte_ms": [200.0] * 5,
        },
        [{"submit_to_first_audio_ms": web_p50}] * 5,
        [{"eos_to_first_audio_ms": phone_p50}] * 5,
        llm_provider="openai",
        timestamp=ts,
    )


def test_measurement_median_and_noise_math():
    reports = [
        _run_report("t1", llm_p50=600.0, web_p50=1800.0, phone_p50=2000.0),
        _run_report("t2", llm_p50=700.0, web_p50=1900.0, phone_p50=2200.0),
        _run_report("t3", llm_p50=900.0, web_p50=1700.0, phone_p50=2100.0),
    ]

    m = latency_bench.build_measurement(reports)

    llm = m["stages"]["llm_ttft_ms"]
    assert llm["median_p50"] == 700.0
    assert llm["noise_pct"] == pytest.approx((900 - 600) / 700 * 100, abs=0.1)
    assert llm["pass"] is True
    assert m["e2e"]["web"]["median_p50"] == 1800.0
    assert m["e2e"]["phone"]["median_p50"] == 2100.0
    assert m["overall_pass"] is True
    assert m["schema_version"] == 3
    assert m["kind"] == "measurement"
    assert m["runs"] == ["t1", "t2", "t3"]
    assert m["timestamp"] == "t3"


def test_measurement_verdict_is_median_not_worst_run():
    # One hung run (llm 5000ms) must NOT fail the measurement when the median passes.
    reports = [
        _run_report("t1", llm_p50=600.0, web_p50=1800.0, phone_p50=2000.0),
        _run_report("t2", llm_p50=5000.0, web_p50=1900.0, phone_p50=2100.0),
        _run_report("t3", llm_p50=700.0, web_p50=1700.0, phone_p50=2200.0),
    ]

    m = latency_bench.build_measurement(reports)

    assert m["stages"]["llm_ttft_ms"]["median_p50"] == 700.0
    assert m["stages"]["llm_ttft_ms"]["pass"] is True
    assert m["overall_pass"] is True


def test_measurement_fails_when_median_over_budget():
    reports = [
        _run_report("t1", llm_p50=1500.0, web_p50=1800.0, phone_p50=2000.0),
        _run_report("t2", llm_p50=1300.0, web_p50=1900.0, phone_p50=2100.0),
        _run_report("t3", llm_p50=600.0, web_p50=1700.0, phone_p50=2200.0),
    ]

    m = latency_bench.build_measurement(reports)

    assert m["stages"]["llm_ttft_ms"]["median_p50"] == 1300.0  # > 1200 budget
    assert m["stages"]["llm_ttft_ms"]["pass"] is False
    assert m["overall_pass"] is False


def test_measurement_e2e_no_data_run_fails_channel():
    good = _run_report("t1", llm_p50=600.0, web_p50=1800.0, phone_p50=2000.0)
    empty_web = latency_bench.build_report(
        {
            "eos_to_stt_ms": [500.0],
            "llm_ttft_ms": [600.0],
            "tts_first_byte_ms": [200.0],
        },
        [],  # web produced no records this run
        [{"eos_to_first_audio_ms": 2000.0}],
        llm_provider="openai",
        timestamp="t2",
    )

    m = latency_bench.build_measurement([good, empty_web])

    assert m["e2e"]["web"]["pass"] is False
    assert m["overall_pass"] is False


def test_measurement_e2e_gated_on_p95_median_too():
    # p50 medians fine, but phone p95 median over 4000 must fail the channel.
    reports = [
        _run_report("t1", llm_p50=600.0, web_p50=1800.0, phone_p50=2000.0),
        _run_report("t2", llm_p50=600.0, web_p50=1800.0, phone_p50=2000.0),
    ]
    for r in reports:
        r["end_to_end"]["phone"]["p95_eos_to_first_audio_ms"] = 4500.0

    m = latency_bench.build_measurement(reports)

    assert m["e2e"]["phone"]["median_p95"] == 4500.0
    assert m["e2e"]["phone"]["pass"] is False


def test_write_measurement_filename_and_roundtrip(tmp_path):
    m = latency_bench.build_measurement(
        [_run_report("t1", llm_p50=600.0, web_p50=1800.0, phone_p50=2000.0)] * 2
    )

    path = latency_bench.write_measurement(m, out_dir=tmp_path)

    assert path.name == "t1-measurement.json"
    assert json.loads(path.read_text())["kind"] == "measurement"


def test_render_measurement_table_shows_noise_and_verdicts():
    reports = [
        _run_report("t1", llm_p50=600.0, web_p50=1800.0, phone_p50=2000.0),
        _run_report("t2", llm_p50=900.0, web_p50=2900.0, phone_p50=2100.0),
        _run_report("t3", llm_p50=700.0, web_p50=1700.0, phone_p50=2200.0),
    ]

    table = latency_bench.render_measurement_table(latency_bench.build_measurement(reports))

    assert "MEASUREMENT (3 runs" in table
    assert "noise%" in table
    assert "e2e web" in table
    assert "measurement overall:" in table


def test_main_repeat_runs_bench_n_times_and_writes_measurement(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.delenv("LATENCY_GATE_HARD", raising=False)

    calls = {"n": 0}

    async def _fake_run_live():
        calls["n"] += 1
        return _run_report(f"t{calls['n']}", llm_p50=600.0, web_p50=1800.0, phone_p50=2000.0)

    written = {}
    monkeypatch.setattr(latency_bench, "_run_live", _fake_run_live)
    monkeypatch.setattr(latency_bench, "write_report", lambda r, out_dir=None: "unused")
    monkeypatch.setattr(
        latency_bench,
        "write_measurement",
        lambda m, out_dir=None: written.setdefault("m", m) or "unused",
    )

    rc = latency_bench.main(["--repeat", "3"])

    assert rc == 0
    assert calls["n"] == 3
    assert written["m"]["runs"] == ["t1", "t2", "t3"]
    assert "MEASUREMENT (3 runs" in capsys.readouterr().out


def test_main_repeat_gate_hard_uses_measurement_verdict(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.setenv("LATENCY_GATE_HARD", "1")

    calls = {"n": 0}

    async def _fake_run_live():
        calls["n"] += 1
        # every run's llm median is over budget -> measurement FAIL
        return _run_report(f"t{calls['n']}", llm_p50=5000.0, web_p50=1800.0, phone_p50=2000.0)

    monkeypatch.setattr(latency_bench, "_run_live", _fake_run_live)
    monkeypatch.setattr(latency_bench, "write_report", lambda r, out_dir=None: "unused")
    monkeypatch.setattr(latency_bench, "write_measurement", lambda m, out_dir=None: "unused")

    assert latency_bench.main(["--repeat", "2"]) == 1


def test_main_repeat_one_preserves_single_run_behavior(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "y")
    monkeypatch.delenv("LATENCY_GATE_HARD", raising=False)

    async def _fake_run_live():
        return _run_report("t1", llm_p50=600.0, web_p50=1800.0, phone_p50=2000.0)

    monkeypatch.setattr(latency_bench, "_run_live", _fake_run_live)
    monkeypatch.setattr(latency_bench, "write_report", lambda r, out_dir=None: "unused")

    rc = latency_bench.main([])

    assert rc == 0
    assert "MEASUREMENT" not in capsys.readouterr().out


# --- perceived-audio visibility rows (loop v2 q0-5) --------------------------------------


def test_e2e_summary_carries_perceived_p50_when_records_have_it():
    records = [
        {"eos_to_first_audio_ms": 2000.0, "first_perceived_audio_ms": 3.0},
        {"eos_to_first_audio_ms": 2200.0, "first_perceived_audio_ms": 5.0},
        {"eos_to_first_audio_ms": 2100.0, "first_perceived_audio_ms": 4.0},
    ]
    from app.latency.budgets import PHONE_E2E

    summary = latency_bench._e2e_summary(records, "eos_to_first_audio_ms", PHONE_E2E)

    assert summary["p50_first_perceived_audio_ms"] == 4.0
    # visibility only: gating is untouched by the perceived row
    assert summary["pass"] is True


def test_e2e_summary_omits_perceived_row_when_absent():
    records = [{"eos_to_first_audio_ms": 2000.0}]
    from app.latency.budgets import PHONE_E2E

    summary = latency_bench._e2e_summary(records, "eos_to_first_audio_ms", PHONE_E2E)

    assert "p50_first_perceived_audio_ms" not in summary


def test_perceived_row_never_gates():
    # A horrible perceived number must not affect pass (visibility only, no budget).
    records = [
        {"eos_to_first_audio_ms": 2000.0, "first_perceived_audio_ms": 99999.0},
    ]
    from app.latency.budgets import PHONE_E2E

    summary = latency_bench._e2e_summary(records, "eos_to_first_audio_ms", PHONE_E2E)

    assert summary["pass"] is True
    assert summary["p50_first_perceived_audio_ms"] == 99999.0
