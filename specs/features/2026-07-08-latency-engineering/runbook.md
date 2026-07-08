# Latency Engineering — Debug Runbook

Companion to `requirements.md`/`plan.md`, filled in as Scope A (harness) and Scope C
(fixes) land. Entry point: run `make latency`, read `data/latency/{ts}.json`'s rendered
table (also printed to stdout), then use the table below to trace a FAIL to a level and
a fix.

## 1. Report column → level → fix

| Report column over budget | Level | Root-cause check | Fix |
|---|---|---|---|
| `eos_to_stt_ms` > 900 | L3 STT | §2 curl TTFB against `api.openai.com` — small network RTT + this still slow ⇒ provider-side | check `OPENAI_STT_MODEL` / the `OPENAI_STT_USE_FALLBACK` flag; no dedicated fix menu item (STT itself isn't a fix target) |
| `stt_to_agent_first_token_ms` (bench's `llm_ttft_ms` is a lower-bound proxy) > 1200 | L4 agent LLM | §2 curl TTFB against `api.deepseek.com` **and** `api.openai.com` side by side — small RTT + big TTFT ⇒ provider-side | **P1-2** (prompt slimming) · **P2-1** (fewer tool round trips) · **P2-2** (provider A/B — decision recorded in requirements.md) |
| `first_token_to_first_sentence_ms` > 800 | L4 chunker | inspect `app/agent/pipeline.py`'s sentence-boundary regex against the actual reply shape | **P1-3** (first-clause chunking) |
| `tts_first_byte_ms` > 500 | L5 TTS | isolate via the micro-bench row alone (rules out L4/L6 contamination) | **P0-1** (static cache, for the constant greeting/filler/fallback strings only) — a regression on dynamic LLM-generated sentences has no dedicated fix item today |
| `first_outbound_frame_ms` (from `bench_e2e_phone`'s per-record deltas) high | L6 bridge | compare against the TTS micro-bench row in isolation — a regression here is resample/mu-law/framing overhead, not TTS itself | no fix item today; treat as a new finding |
| e2e `eos_to_first_audio_ms` (phone) / `submit_to_first_audio_ms` (web) p50 > 2500 or p95 > 4000 | composite | read the other columns in the same report first — this is the roll-up, not an independent diagnosis | trace to whichever single stage above is over budget |
| answer→greeting slow | L5 (greeting synth) | `ls data/tts_cache/` — is it populated? | **P0-1** |
| filler audible > 800ms after eos | L4-perceived | is the filler still gated on `ToolInvoked` instead of eos/submit? | **P0-2** |
| `turn_total_ms` regression with every upstream stage passing | L7 app overhead | is `persist_session`/the recording write still `await`ed inline instead of backgrounded? | **P1-1** (phone-side only this pass — see requirements.md's scope note on the web-channel exception) |

Note: `tts_first_byte_ms` and `first_outbound_frame_ms` are currently only produced by
`make latency`'s bench functions, not by a real live call — telephony plan group 5b's
structured observability events (which would carry these from production) aren't
implemented yet. Until 5b lands, trust the bench numbers for these two columns and use
§3 below for everything else on a real call.

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

Every real turn logs one `turn_trace channel=<phone|web> session=<id> ...` INFO line
(`app/agent/trace.py`'s `log_turn_trace`, called from `app/phone/real_agent.py` and
`app/ws/routes.py`) with the same named fields as the bench report. Correlate a slow
call to a specific turn by grepping for its session id:

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
