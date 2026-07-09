"""Twilio CLI debugging toolkit (specs/features/2026-07-08-twilio-cli-debug).

A failed call's evidence is spread across four surfaces — Twilio (webhook config,
call status, monitor alerts), the ngrok tunnel, the app's structured ``twilio.*``
events, and the DB/recordings. This script joins them from one CLI.

Design (requirements.md Decisions):
1. Wraps the already-authenticated ``twilio-cli`` via subprocess (``-o json``) —
   never reimplements its REST client. HTTP is used only for ngrok's local API,
   the app's own endpoints, and authenticated recording downloads.
2. Read-only by default; ``wire`` is the single mutating subcommand and dry-runs
   unless ``--yes`` is passed. It only ever touches the recorded number SID.
3. ``simulate`` reuses ``app/phone/signature.py`` — a passing simulate exercises
   exactly the code path a real Twilio POST hits (incl. the ``PUBLIC_HOST``
   branch of ``_webhook_url``).
4. No secrets in output — the auth token is never printed and API-key-shaped
   strings are scrubbed; phone numbers render as last-4.
5. ``call_sid`` is the correlation key across Twilio API ↔ app logs ↔ ``sessions``
   ↔ recordings.

Run via ``make phone-debug cmd="status"`` or ``python scripts/twilio_debug.py <cmd>``.
The symptom → subcommand runbook lives in the spec's requirements.md and the README.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

# Recorded number (requirements.md §Grounding); overridable for other accounts.
DEFAULT_NUMBER_SID = "PN356e3d2a44afd34496997e66fb547da2"
DEFAULT_NUMBER = "+13186468479"

_SECRET_SHAPES = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b|\bSK[0-9a-f]{32}\b")
_FULL_NUMBER = re.compile(r"\+\d{7,15}\b")


def _number_sid() -> str:
    return os.environ.get("TWILIO_PHONE_NUMBER_SID", DEFAULT_NUMBER_SID)


def _app_url() -> str:
    return os.environ.get("PHONE_DEBUG_APP_URL", "http://localhost:8000").rstrip("/")


def _ngrok_api_url() -> str:
    return os.environ.get("NGROK_API_URL", "http://localhost:4040").rstrip("/")


# --- redaction (requirements.md Decision 4) --------------------------------------


def mask_number(value: str | None) -> str:
    """Render a phone number as last-4 (``+13186468479`` → ``…8479``)."""
    if not value:
        return "?"
    digits = re.sub(r"\D", "", value)
    return f"…{digits[-4:]}" if len(digits) >= 4 else "…"


def redact(text: str) -> str:
    """Scrub the auth token, API-key-shaped strings, and full phone numbers."""
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if token:
        text = text.replace(token, "***TWILIO_AUTH_TOKEN***")
    text = _SECRET_SHAPES.sub("***REDACTED***", text)
    return _FULL_NUMBER.sub(lambda m: mask_number(m.group()), text)


def say(text: str = "") -> None:
    print(redact(text))


# --- twilio-cli subprocess wrapper (requirements.md Decision 1) -------------------


def run_twilio(args: list[str]) -> Any:
    """Shell out to ``twilio <args> -o json`` and parse the JSON. Returns None on
    failure (stderr echoed, redacted) so read-only subcommands degrade gracefully."""
    cmd = ["twilio", *args, "-o", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        say("twilio-cli not found on PATH — install/auth it first (profile `vadim`).")
        return None
    if proc.returncode != 0:
        say(f"twilio-cli failed ({' '.join(args[:1])}): {proc.stderr.strip()}")
        return None
    out = proc.stdout.strip()
    if not out:
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        say(f"twilio-cli returned non-JSON output: {out[:200]}")
        return None


def _first(record: Any) -> dict[str, Any]:
    """twilio-cli ``-o json`` returns a list even for fetch — normalize to one dict."""
    if isinstance(record, list):
        return record[0] if record else {}
    return record or {}


# --- ngrok tunnel discovery --------------------------------------------------------


def resolve_ngrok_url(payload: dict[str, Any]) -> str | None:
    """Pick the https public URL out of ngrok's ``/api/tunnels`` JSON."""
    for tunnel in payload.get("tunnels", []):
        url = tunnel.get("public_url", "")
        if url.startswith("https://"):
            return url
    return None


def ngrok_public_url() -> str | None:
    try:
        response = httpx.get(f"{_ngrok_api_url()}/api/tunnels", timeout=3.0)
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - tunnel simply not running
        return None
    return resolve_ngrok_url(response.json())


def derive_endpoints(public_url: str) -> dict[str, str]:
    """Public base URL → the two endpoints Twilio must reach."""
    base = public_url.rstrip("/")
    host = base.split("://", 1)[1] if "://" in base else base
    return {"voice_url": f"{base}/twilio/voice", "stream_url": f"wss://{host}/ws/twilio"}


def resolve_public_url() -> str | None:
    """ngrok tunnel first (dev), else ``PUBLIC_HOST`` (hosted)."""
    url = ngrok_public_url()
    if url:
        return url
    public_host = os.environ.get("PUBLIC_HOST", "").strip()
    if not public_host:
        return None
    if not public_host.startswith(("http://", "https://")):
        public_host = f"https://{public_host}"
    return public_host


# --- subcommands -------------------------------------------------------------------


def fetch_number() -> dict[str, Any]:
    return _first(
        run_twilio(
            [
                "api:core:incoming-phone-numbers:fetch",
                "--sid",
                _number_sid(),
                "--properties",
                "sid,phoneNumber,voiceUrl,voiceMethod",
            ]
        )
    )


def cmd_status(_args: argparse.Namespace) -> int:
    number = fetch_number()
    voice_url = number.get("voiceUrl") or "?"
    say(f"number       : {mask_number(number.get('phoneNumber', DEFAULT_NUMBER))}")
    say(f"webhook      : {number.get('voiceMethod', '?')} {voice_url}")

    tunnel = ngrok_public_url()
    say(f"ngrok tunnel : {tunnel or 'not running'}")

    try:
        health = httpx.get(f"{_app_url()}/healthz", timeout=3.0)
        say(f"app /healthz : {health.status_code}")
    except Exception:  # noqa: BLE001 - app simply not up
        say(f"app /healthz : unreachable at {_app_url()}")

    public = tunnel or resolve_public_url()
    if public:
        expected = derive_endpoints(public)["voice_url"]
        if voice_url != expected:
            say(f"MISMATCH     : webhook != {expected} — run `wire --yes` to repair")
            return 1
        say("webhook OK   : matches the current public URL")
    else:
        say("no public URL (ngrok down, PUBLIC_HOST unset) — cannot check for mismatch")
    return 0


def cmd_wire(args: argparse.Namespace) -> int:
    public = resolve_public_url()
    if public is None:
        say("no public URL: start the ngrok profile or set PUBLIC_HOST")
        return 1
    proposed = derive_endpoints(public)["voice_url"]
    before = fetch_number()
    say(f"current voiceUrl : {before.get('voiceUrl', '?')}")
    say(f"proposed voiceUrl: {proposed}")
    if not args.yes:
        say("dry run — pass --yes to apply (the single mutating subcommand)")
        return 0
    run_twilio(
        [
            "api:core:incoming-phone-numbers:update",
            "--sid",
            _number_sid(),
            "--voice-url",
            proposed,
            "--voice-method",
            "POST",
        ]
    )
    after = fetch_number()
    say(f"after voiceUrl   : {after.get('voiceUrl', '?')}")
    return 0 if after.get("voiceUrl") == proposed else 1


def cmd_calls(args: argparse.Namespace) -> int:
    calls = run_twilio(["api:core:calls:list", "--limit", str(args.limit)])
    if calls is None:
        return 1
    if not calls:
        say("no calls found")
        return 0
    for call in calls:
        say(
            f"{call.get('sid')}  {call.get('status'):<11} {call.get('duration') or '-':>4}s  "
            f"from {mask_number(call.get('from'))}  {call.get('startTime') or ''}"
        )
    return 0


def _grep_app_logs(needle: str) -> list[str]:
    """Best-effort read of the Compose app service's recent logs."""
    try:
        proc = subprocess.run(
            ["docker", "compose", "logs", "--no-color", "app"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:  # noqa: BLE001 - docker not running is a normal dev state
        return []
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if needle in line]


_SESSION_ID = re.compile(r"session[_=\s\"']+([0-9a-f]{8}-[0-9a-f-]{27,})", re.IGNORECASE)


def cmd_call(args: argparse.Namespace) -> int:
    detail = _first(run_twilio(["api:core:calls:fetch", "--sid", args.call_sid]))
    if detail:
        say(
            f"{detail.get('sid')}  {detail.get('status')}  {detail.get('duration') or '-'}s  "
            f"from {mask_number(detail.get('from'))} to {mask_number(detail.get('to'))}"
        )
    lines = _grep_app_logs(args.call_sid)
    session_id: str | None = None
    for line in lines:
        match = _SESSION_ID.search(line)
        if match:
            session_id = match.group(1)
            break
    say(f"app log lines mentioning the call: {len(lines)}")
    for line in lines[-args.log_lines :]:
        say(f"  {line.strip()}")
    if session_id:
        say(f"session_id   : {session_id} (sessions row: SELECT * FROM sessions WHERE id = '…')")
        recordings_dir = Path(os.environ.get("RECORDINGS_DIR", "data/recordings")) / session_id
        if recordings_dir.is_dir():
            files = sorted(p.name for p in recordings_dir.iterdir())
            say(f"recordings   : {recordings_dir} ({len(files)} files)")
        else:
            say(f"recordings   : none at {recordings_dir}")
    else:
        say("session_id   : not found in app logs (is the Compose app service running?)")
    return 0


def cmd_alerts(args: argparse.Namespace) -> int:
    alerts = run_twilio(["api:monitor:alerts:list", "--limit", str(args.limit)])
    if alerts is None:
        return 1
    if not alerts:
        say("no alerts — Twilio reached the webhook without errors")
        return 0
    for alert in alerts:
        say(
            f"{alert.get('dateGenerated') or alert.get('dateCreated')}  "
            f"error {alert.get('errorCode')}  {alert.get('logLevel')}  "
            f"{(alert.get('alertText') or '')[:120]}"
        )
    return 0


def build_simulate_form(to_number: str | None = None) -> dict[str, str]:
    """A synthetic inbound-call webhook form (the fields the app actually reads)."""
    return {
        "CallSid": f"CA{uuid.uuid4().hex}",
        "AccountSid": os.environ.get("TWILIO_ACCOUNT_SID", f"AC{uuid.uuid4().hex}"),
        "From": "+15005550006",  # Twilio's magic test number
        "To": to_number or os.environ.get("TWILIO_PHONE_NUMBER", DEFAULT_NUMBER),
        "CallStatus": "ringing",
        "Direction": "inbound",
    }


def signing_url() -> str:
    """The URL to sign against — mirrors ``app/phone/webhook.py::_webhook_url``:
    ``PUBLIC_HOST`` wins when set, else the local app URL."""
    public_host = os.environ.get("PUBLIC_HOST", "").strip()
    if not public_host:
        return f"{_app_url()}/twilio/voice"
    if not public_host.startswith(("http://", "https://")):
        public_host = f"https://{public_host}"
    return f"{public_host.rstrip('/')}/twilio/voice"


def compute_signature(url: str, params: dict[str, str]) -> str:
    from app.phone.signature import get_validator

    return get_validator().compute_signature(url, params)


def cmd_simulate(_args: argparse.Namespace) -> int:
    if not os.environ.get("TWILIO_AUTH_TOKEN"):
        say("TWILIO_AUTH_TOKEN not set — simulate needs it to sign the synthetic request")
        return 1
    form = build_simulate_form()
    url = signing_url()
    signature = compute_signature(url, form)
    post_url = f"{_app_url()}/twilio/voice"
    say(f"signing URL : {url}")
    say(f"POST        : {post_url} (CallSid {form['CallSid']})")
    try:
        response = httpx.post(
            post_url,
            data=form,
            headers={"X-Twilio-Signature": signature},
            timeout=10.0,
        )
    except Exception as exc:  # noqa: BLE001 - app not running is the finding itself
        say(f"POST failed : {type(exc).__name__} — is the app running at {_app_url()}?")
        return 1
    say(f"status      : {response.status_code}")
    say(response.text)
    return 0 if response.status_code == 200 else 1


def cmd_tail(args: argparse.Namespace) -> int:
    """Follow ``docker compose logs -f app`` filtered to ``twilio.*`` structured events."""
    needle = args.call_sid or "twilio."
    try:
        proc = subprocess.Popen(
            ["docker", "compose", "logs", "-f", "--no-color", "app"],
            stdout=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        say("docker not found — tail needs the Compose app service")
        return 1
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if needle in line:
                say(line.rstrip())
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return 0


def cmd_recordings(args: argparse.Namespace) -> int:
    recordings = run_twilio(["api:core:recordings:list", "--limit", str(args.limit)])
    if recordings is None:
        return 1
    if args.call_sid:
        recordings = [r for r in recordings if r.get("callSid") == args.call_sid]
    if not recordings:
        say("no Twilio-side recordings found")
        return 0
    for rec in recordings:
        say(
            f"{rec.get('sid')}  call {rec.get('callSid')}  {rec.get('duration') or '-'}s  "
            f"{rec.get('channels')}ch  {rec.get('source')}  {rec.get('dateCreated') or ''}"
        )
    if args.download:
        sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        if not sid or not token:
            say("download needs TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN in the env")
            return 1
        media_url = (
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Recordings/{args.download}.mp3"
        )
        out_path = Path(f"{args.download}.mp3")
        response = httpx.get(media_url, auth=(sid, token), timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        out_path.write_bytes(response.content)
        say(f"downloaded  : {out_path} ({len(response.content)} bytes)")
    return 0


# --- entrypoint --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twilio_debug",
        description="Debug the Twilio phone channel from one CLI (see spec runbook).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="webhook URL vs tunnel/PUBLIC_HOST + /healthz, flags mismatch")

    wire = sub.add_parser("wire", help="point the number's voice webhook at the current tunnel")
    wire.add_argument("--yes", action="store_true", help="apply (dry-run without it)")

    calls = sub.add_parser("calls", help="recent calls (sid, status, duration, from last-4)")
    calls.add_argument("--limit", type=int, default=5)

    call = sub.add_parser("call", help="one call: Twilio detail + correlated app-side view")
    call.add_argument("call_sid")
    call.add_argument("--log-lines", type=int, default=20)

    alerts = sub.add_parser("alerts", help="Twilio monitor alerts (11200 webhook failures etc.)")
    alerts.add_argument("--limit", type=int, default=10)

    sub.add_parser("simulate", help="signed synthetic inbound-call POST to the local webhook")

    tail = sub.add_parser("tail", help="follow app logs filtered to twilio.* events")
    tail.add_argument("--call-sid", default=None)

    recordings = sub.add_parser("recordings", help="Twilio-side recordings (+ optional download)")
    recordings.add_argument("--call-sid", default=None)
    recordings.add_argument("--limit", type=int, default=10)
    recordings.add_argument("--download", metavar="RE_SID", default=None)

    return parser


_COMMANDS = {
    "status": cmd_status,
    "wire": cmd_wire,
    "calls": cmd_calls,
    "call": cmd_call,
    "alerts": cmd_alerts,
    "simulate": cmd_simulate,
    "tail": cmd_tail,
    "recordings": cmd_recordings,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
