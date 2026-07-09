# Latency Engineering — Debug Runbook

Companion to `requirements.md`/`plan.md`, filled in as Scope A (harness) and Scope C
(fixes) land. Entry point: run `make latency`, read `data/latency/{ts}.json`'s rendered
table (also printed to stdout), then use the table below to trace a FAIL to a level and
a fix.

## 1. Report column → level → fix

> **Phone path re-homed to Pipecat (2026-07-09).** On the **phone** channel, endpointing,
> STT, streaming TTS, and µ-law framing are now Pipecat services/internals (`app/voice/`,
> `specs/features/2026-07-09-pipecat-voice-port/`); the phone stage numbers come from
> Pipecat's per-call metrics (`PipelineParams(enable_metrics=True)` in `app/voice/bot.py`),
> not the deleted `app/phone/{vad,bridge,real_agent}.py`. `make latency`'s
> `bench_e2e_phone` now measures the provider-independent LLM+TTS stack directly (bridge
> dropped). The fixes below still name the code to change for the **web** channel; the
> "Fix" column's phone-only items (P0-1/P0-2/P1-1 phone halves, the L6 bridge row) are
> superseded — retune the Pipecat service instead. The composite e2e envelope
> (p50 ≤ 2.5 s / p95 ≤ 4 s) still applies to both channels.

| Report column over budget | Level | Root-cause check | Fix |
|---|---|---|---|
| `eos_to_stt_ms` > 900 | L3 STT | §2 curl TTFB against `api.openai.com`/`api.deepgram.com` — small network RTT + this still slow ⇒ provider-side | phone: Pipecat STT service (Deepgram default; `STT_PROVIDER=openai` swaps back) — no app fix target. web: check `OPENAI_STT_MODEL` / `OPENAI_STT_USE_FALLBACK` |
| `stt_to_agent_first_token_ms` (bench's `llm_ttft_ms` is a lower-bound proxy) > 1200 | L4 agent LLM | §2 curl TTFB against `api.deepseek.com` **and** `api.openai.com` side by side — small RTT + big TTFT ⇒ provider-side | **P1-2** (prompt slimming, web) · **P2-1** (fewer tool round trips) · **P2-2** (provider A/B — decision in requirements.md). Phone LLM = Pipecat `OpenAILLMService` (`VOICE_LLM_MODEL`, default gpt-4o) |
| `first_token_to_first_sentence_ms` > 800 | L4 chunker | web: inspect `app/agent/pipeline.py`'s sentence-boundary regex against the actual reply shape | **P1-3** (first-clause chunking, web). *Phone: no app chunker — Pipecat's LLM→TTS seam streams tokens directly* |
| `tts_first_byte_ms` > 500 | L5 TTS | isolate via the micro-bench row alone (rules out L4/L6 contamination) | web: **P0-1** (static cache for constant strings). Phone: Pipecat streaming TTS (`gpt-4o-mini-tts`; `TTS_PROVIDER` swaps to Cartesia/Deepgram Aura-2) — no app cache |
| `first_outbound_frame_ms` high | L6 framing | web: compare against the TTS micro-bench row in isolation. Phone: this was the deleted `bridge.py` resample/µ-law step — now the Pipecat `TwilioFrameSerializer` | phone: read Pipecat metrics — resample/µ-law/framing is serializer-internal; treat a regression as a new finding. No app fix item |
| e2e `eos_to_first_audio_ms` (phone) / `submit_to_first_audio_ms` (web) p50 > 2500 or p95 > 4000 | composite | read the other columns in the same report first — this is the roll-up, not an independent diagnosis | trace to whichever single stage above is over budget |
| answer→greeting slow | L5 (greeting) | web: `ls data/tts_cache/` — is it populated? Phone: is the constant `TTSSpeakFrame(GREETING)` still queued on connect (no LLM round trip)? | web: **P0-1**. Phone: check the `on_client_connected` handler in `app/voice/bot.py` |
| filler audible > 800ms after eos | L4-perceived (web) | web: is the filler still gated on `ToolInvoked` instead of submit? | **P0-2** (web). *Phone: N/A — Pipecat streams the first token to TTS with native barge-in; no dead-air window* |
| `turn_total_ms` regression with every upstream stage passing | L7 app overhead | web: is `persist_session`/the recording write still `await`ed inline instead of backgrounded? | **P1-1** (web). *Phone: Pipecat owns per-call session/memory; cross-call persist deferred (pipecat-voice-port § Not included)* |

Note: on the **phone** channel these columns now come from Pipecat's per-call metrics
(`enable_metrics=True`) rather than the bench/bridge code, which was deleted with
`app/phone/`. On the **web** channel `tts_first_byte_ms` and `first_outbound_frame_ms` are
still produced by `make latency`'s bench functions, not a real live call — trust the bench
numbers for those two columns and use §3 below for everything else on a real call.

## 2. Network-vs-provider separation (no packet capture needed)

```bash
curl -s -o /dev/null -w 'dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' https://api.deepseek.com/
curl -s -o /dev/null -w 'dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' https://api.openai.com/
curl -s -o /dev/null -w 'dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' "<ngrok tunnel URL or PUBLIC_HOST>/healthz"
```

Rule of thumb: if the tunnel/provider `ttfb` numbers here are small and
`make latency`'s `stt_to_agent_first_token_ms`/`llm_ttft_ms` is still big, the lag is
provider-side (L4), not the tunnel hop (L1) — this is what separates P2-2 (provider A/B)
from P2-3 (kill the tunnel) as the right fix.

## 3. Live-call correlation

**Web:** every real turn logs one `turn_trace channel=web session=<id> ...` INFO line
(`app/agent/trace.py`'s `log_turn_trace`, called from `app/ws/routes.py`) with the same
named fields as the bench report.

**Phone (Pipecat):** the deleted `app/phone/real_agent.py` no longer emits `turn_trace`;
per-call phone timing comes from Pipecat's pipeline metrics
(`PipelineParams(enable_metrics=True, enable_usage_metrics=True)` in `app/voice/bot.py`),
which report per-stage (VAD/STT/LLM/TTS) processing and TTFB metrics per call — the phone
mapping of the same stage columns. Correlate a slow call by its session/call SID
(`app.voice.bot` logs `voice_call_connected`/`voice_call_ended` with `call=` and
`session=`).

Grep either stream by id:

```bash
docker compose logs -f app | grep <session_id>
```

`scripts/twilio_debug.py tail --call-sid <CallSid>` (spec'd in
`specs/features/2026-07-08-twilio-cli-debug/`) is the intended purpose-built tool for
this once it lands — it isn't implemented yet, so the `docker compose logs` grep above
is the interim path.

## 4. Gate status

Advisory today (`make latency` always exits 0 unless `LATENCY_GATE_HARD=1` is set).
Flips to hard-by-default only after two consecutive all-PASS runs — see
`requirements.md` Decision 3 and `plan.md` step 6.
