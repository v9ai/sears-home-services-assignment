"""Offline units for the Twilio CLI debug toolkit (twilio-cli-debug validation.md).

No Twilio API calls: the twilio-cli wrapper is spied/monkeypatched, ngrok resolution
runs against fixture JSON, and simulate's signing round-trips through the app's own
``app/phone/signature.validate_request``.
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import pytest

from app.phone.signature import validate_request
from scripts import twilio_debug


@pytest.fixture(autouse=True)
def _auth_token(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-auth-token-0123456789abcdef")


# --- simulate signing round-trip ---------------------------------------------------


def test_simulate_signature_accepted_by_app_validator(monkeypatch):
    monkeypatch.delenv("PUBLIC_HOST", raising=False)
    form = twilio_debug.build_simulate_form()
    url = twilio_debug.signing_url()
    signature = twilio_debug.compute_signature(url, form)
    assert url == "http://localhost:8000/twilio/voice"
    assert validate_request(url, form, signature) is True


def test_simulate_signs_against_public_host_when_set(monkeypatch):
    # The PUBLIC_HOST-differs-from-request-host case: Twilio signs the public URL,
    # not the URL the local process sees (app/phone/webhook.py::_webhook_url).
    monkeypatch.setenv("PUBLIC_HOST", "example.ngrok.app")
    form = twilio_debug.build_simulate_form()
    url = twilio_debug.signing_url()
    signature = twilio_debug.compute_signature(url, form)
    assert url == "https://example.ngrok.app/twilio/voice"
    assert validate_request(url, form, signature) is True
    # A signature computed for the local URL must NOT validate against the public one.
    local_signature = twilio_debug.compute_signature("http://localhost:8000/twilio/voice", form)
    assert validate_request(url, form, local_signature) is False


# --- ngrok tunnel resolution --------------------------------------------------------

_TUNNELS_FIXTURE = {
    "tunnels": [
        {"public_url": "http://abc123.ngrok.app", "proto": "http"},
        {"public_url": "https://abc123.ngrok.app", "proto": "https"},
    ]
}


def test_resolve_ngrok_url_prefers_https():
    assert twilio_debug.resolve_ngrok_url(_TUNNELS_FIXTURE) == "https://abc123.ngrok.app"


def test_resolve_ngrok_url_empty_payload():
    assert twilio_debug.resolve_ngrok_url({"tunnels": []}) is None


def test_derive_endpoints():
    endpoints = twilio_debug.derive_endpoints("https://abc123.ngrok.app/")
    assert endpoints["voice_url"] == "https://abc123.ngrok.app/twilio/voice"
    assert endpoints["stream_url"] == "wss://abc123.ngrok.app/ws/twilio"


# --- wire dry-run guard --------------------------------------------------------------


def _spy_twilio(calls: list[list[str]], voice_url: str = "https://stale.ngrok.app/twilio/voice"):
    def fake_run_twilio(args: list[str]):
        calls.append(args)
        return [{"sid": "PN356e", "phoneNumber": "+13186468479", "voiceUrl": voice_url}]

    return fake_run_twilio


def test_wire_without_yes_never_updates(monkeypatch, capsys):
    calls: list[list[str]] = []
    monkeypatch.setattr(twilio_debug, "run_twilio", _spy_twilio(calls))
    monkeypatch.setattr(twilio_debug, "resolve_public_url", lambda: "https://fresh.ngrok.app")

    exit_code = twilio_debug.cmd_wire(argparse.Namespace(yes=False))

    assert exit_code == 0
    assert all("update" not in " ".join(call) for call in calls)
    out = capsys.readouterr().out
    assert "https://stale.ngrok.app/twilio/voice" in out  # current
    assert "https://fresh.ngrok.app/twilio/voice" in out  # proposed
    assert "dry run" in out


def test_wire_with_yes_updates_the_recorded_sid_only(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        twilio_debug, "run_twilio", _spy_twilio(calls, "https://fresh.ngrok.app/twilio/voice")
    )
    monkeypatch.setattr(twilio_debug, "resolve_public_url", lambda: "https://fresh.ngrok.app")

    exit_code = twilio_debug.cmd_wire(argparse.Namespace(yes=True))

    assert exit_code == 0
    updates = [call for call in calls if call[0].endswith(":update")]
    assert len(updates) == 1
    assert twilio_debug.DEFAULT_NUMBER_SID in updates[0]
    assert "--voice-method" in updates[0] and "POST" in updates[0]


# --- output redaction -----------------------------------------------------------------


def test_redact_scrubs_token_keys_and_numbers(monkeypatch):
    text = "token=test-auth-token-0123456789abcdef key=sk-abcdef1234567890 caller=+13186468479 done"
    redacted = twilio_debug.redact(text)
    assert "test-auth-token-0123456789abcdef" not in redacted
    assert "sk-abcdef1234567890" not in redacted
    assert "+13186468479" not in redacted
    assert "…8479" in redacted


def test_mask_number_last4():
    assert twilio_debug.mask_number("+13186468479") == "…8479"
    assert twilio_debug.mask_number(None) == "?"


def test_calls_output_masks_numbers(monkeypatch, capsys):
    monkeypatch.setattr(
        twilio_debug,
        "run_twilio",
        lambda args: [
            {
                "sid": "CA123",
                "status": "completed",
                "duration": "42",
                "from": "+13125550123",
                "startTime": "2026-07-09",
            }
        ],
    )
    assert twilio_debug.cmd_calls(argparse.Namespace(limit=5)) == 0
    out = capsys.readouterr().out
    assert "+13125550123" not in out
    assert "…0123" in out


def test_redact_scrubs_sk_hex_shape_without_a_token_env(monkeypatch):
    # No TWILIO_AUTH_TOKEN in the env: the shape-based scrubbers must still fire so a
    # secret never rides through just because the token wasn't set.
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    # Built at runtime so the literal never trips secret scanners (it is a
    # synthetic fixture, but GitHub push protection pattern-matches the shape).
    sk_key = "SK" + "0123456789abcdef" * 2
    redacted = twilio_debug.redact(f"account {sk_key} done")
    assert sk_key not in redacted
    assert "***REDACTED***" in redacted


def test_mask_number_too_short_returns_placeholder():
    assert twilio_debug.mask_number("+12") == "…"


# --- twilio-cli subprocess wrapper: graceful degradation (never raises to the caller) ---


def _fake_completed(returncode: int, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_twilio_missing_cli_returns_none_with_message(monkeypatch, capsys):
    def _raise(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(twilio_debug.subprocess, "run", _raise)
    assert twilio_debug.run_twilio(["api:core:calls:list"]) is None
    assert "twilio-cli not found" in capsys.readouterr().out


def test_run_twilio_nonzero_exit_returns_none_with_stderr(monkeypatch, capsys):
    monkeypatch.setattr(
        twilio_debug.subprocess, "run", lambda *a, **k: _fake_completed(1, stderr="boom")
    )
    assert twilio_debug.run_twilio(["api:core:calls:list"]) is None
    assert "twilio-cli failed" in capsys.readouterr().out


def test_run_twilio_empty_output_is_empty_list(monkeypatch):
    monkeypatch.setattr(twilio_debug.subprocess, "run", lambda *a, **k: _fake_completed(0, "   "))
    assert twilio_debug.run_twilio(["x"]) == []


def test_run_twilio_non_json_returns_none_with_message(monkeypatch, capsys):
    monkeypatch.setattr(
        twilio_debug.subprocess, "run", lambda *a, **k: _fake_completed(0, "not json")
    )
    assert twilio_debug.run_twilio(["x"]) is None
    assert "non-JSON" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ([{"a": 1}, {"b": 2}], {"a": 1}),
        ([], {}),
        ({"x": 1}, {"x": 1}),
        (None, {}),
    ],
)
def test_first_normalizes_twilio_cli_shapes(record, expected):
    assert twilio_debug._first(record) == expected


# --- public-URL resolution (ngrok first, then PUBLIC_HOST) ----------------------------


def test_ngrok_public_url_returns_none_when_tunnel_down(monkeypatch):
    def _raise(*_a, **_k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(twilio_debug.httpx, "get", _raise)
    assert twilio_debug.ngrok_public_url() is None


def test_resolve_public_url_prefers_ngrok(monkeypatch):
    monkeypatch.setattr(twilio_debug, "ngrok_public_url", lambda: "https://tunnel.ngrok.app")
    monkeypatch.setenv("PUBLIC_HOST", "ignored.example")
    assert twilio_debug.resolve_public_url() == "https://tunnel.ngrok.app"


def test_resolve_public_url_falls_back_to_public_host_and_adds_scheme(monkeypatch):
    monkeypatch.setattr(twilio_debug, "ngrok_public_url", lambda: None)
    monkeypatch.setenv("PUBLIC_HOST", "myhost.ngrok.app")
    assert twilio_debug.resolve_public_url() == "https://myhost.ngrok.app"


def test_resolve_public_url_keeps_an_explicit_scheme(monkeypatch):
    monkeypatch.setattr(twilio_debug, "ngrok_public_url", lambda: None)
    monkeypatch.setenv("PUBLIC_HOST", "http://already.scheme")
    assert twilio_debug.resolve_public_url() == "http://already.scheme"


def test_resolve_public_url_none_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(twilio_debug, "ngrok_public_url", lambda: None)
    monkeypatch.delenv("PUBLIC_HOST", raising=False)
    assert twilio_debug.resolve_public_url() is None


# --- read-only subcommands degrade to a clear message + nonzero exit -------------------


def test_calls_empty_and_error_paths(monkeypatch, capsys):
    monkeypatch.setattr(twilio_debug, "run_twilio", lambda args: [])
    assert twilio_debug.cmd_calls(argparse.Namespace(limit=5)) == 0
    assert "no calls found" in capsys.readouterr().out

    monkeypatch.setattr(twilio_debug, "run_twilio", lambda args: None)
    assert twilio_debug.cmd_calls(argparse.Namespace(limit=5)) == 1


def test_alerts_formats_rows_and_handles_none(monkeypatch, capsys):
    monkeypatch.setattr(
        twilio_debug,
        "run_twilio",
        lambda args: [
            {
                "dateGenerated": "2026-07-09",
                "errorCode": "11200",
                "logLevel": "error",
                "alertText": "HTTP retrieval failure",
            }
        ],
    )
    assert twilio_debug.cmd_alerts(argparse.Namespace(limit=10)) == 0
    out = capsys.readouterr().out
    assert "11200" in out and "HTTP retrieval failure" in out

    monkeypatch.setattr(twilio_debug, "run_twilio", lambda args: None)
    assert twilio_debug.cmd_alerts(argparse.Namespace(limit=10)) == 1


def test_recordings_filters_by_call_sid_and_download_needs_creds(monkeypatch, capsys):
    monkeypatch.setattr(
        twilio_debug,
        "run_twilio",
        lambda args: [
            {"sid": "RE1", "callSid": "CA_match", "duration": "12", "channels": 2, "source": "x"},
            {"sid": "RE2", "callSid": "CA_other", "duration": "8", "channels": 1, "source": "x"},
        ],
    )
    assert (
        twilio_debug.cmd_recordings(
            argparse.Namespace(call_sid="CA_match", limit=10, download=None)
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "RE1" in out and "RE2" not in out

    # download requested but the account creds are absent → clear message, nonzero exit,
    # and crucially no network call is attempted.
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    assert (
        twilio_debug.cmd_recordings(argparse.Namespace(call_sid=None, limit=10, download="RE1"))
        == 1
    )
    assert "download needs" in capsys.readouterr().out


def test_simulate_without_auth_token_degrades_and_never_signs(monkeypatch, capsys):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    assert twilio_debug.cmd_simulate(argparse.Namespace()) == 1
    assert "TWILIO_AUTH_TOKEN not set" in capsys.readouterr().out


def test_status_flags_webhook_mismatch(monkeypatch, capsys):
    monkeypatch.setattr(
        twilio_debug,
        "fetch_number",
        lambda: {
            "phoneNumber": "+13186468479",
            "voiceMethod": "POST",
            "voiceUrl": "https://stale/twilio/voice",
        },
    )
    monkeypatch.setattr(twilio_debug, "ngrok_public_url", lambda: "https://fresh.ngrok.app")

    def _boom(*_a, **_k):
        raise RuntimeError("app down")

    monkeypatch.setattr(twilio_debug.httpx, "get", _boom)  # /healthz unreachable
    assert twilio_debug.cmd_status(argparse.Namespace()) == 1
    assert "MISMATCH" in capsys.readouterr().out


# --- CLI dispatch + argument handling -------------------------------------------------


def test_commands_table_matches_the_declared_subparsers():
    """Every declared subcommand has a handler and vice versa — a missing entry would make
    `main` KeyError at dispatch, an extra one is dead code."""
    parser = twilio_debug.build_parser()
    choices: set[str] = set()
    for action in parser._subparsers._group_actions:  # type: ignore[attr-defined]
        if getattr(action, "choices", None):
            choices |= set(action.choices)
    assert choices == set(twilio_debug._COMMANDS)


def test_main_dispatches_to_the_named_handler(monkeypatch):
    seen: dict[str, object] = {}

    def _spy(args):
        seen["args"] = args
        return 0

    monkeypatch.setitem(twilio_debug._COMMANDS, "status", _spy)
    assert twilio_debug.main(["status"]) == 0
    assert seen["args"].command == "status"


def test_main_dispatches_positional_arg_to_call(monkeypatch):
    seen: dict[str, object] = {}

    def _spy(args):
        seen["sid"] = args.call_sid
        return 0

    monkeypatch.setitem(twilio_debug._COMMANDS, "call", _spy)
    assert twilio_debug.main(["call", "CA123"]) == 0
    assert seen["sid"] == "CA123"


@pytest.mark.parametrize("argv", [[], ["bogus"], ["calls", "--limit", "not-an-int"]])
def test_main_rejects_missing_or_invalid_args(argv):
    with pytest.raises(SystemExit) as exc:
        twilio_debug.main(argv)
    assert exc.value.code == 2  # argparse usage error
