"""Cloudflare worker env-forwarding contract (bugfix-loop B4).

`cloudflare/app-worker.ts` forwards only the env names in
``APP_CONTAINER_ENV_NAMES`` into the hosted app container. Any documented
runtime variable missing from that allowlist silently never reaches the
container — the audit found `UPLOAD_TOKEN_SECRET` absent, and the entire
voice-provider block (Deepgram STT, Cartesia TTS) turned out to be missing
too, which would leave hosted phone calls without STT/TTS credentials.

These are plain-text parsing tests (same style as test_compose_config.py):
no TS toolchain required, and drift in either direction fails loudly.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKER = (REPO / "cloudflare" / "app-worker.ts").read_text()
ENV_EXAMPLE = (REPO / ".env.example").read_text()

# Compose-only variables that the hosted container legitimately never needs.
_COMPOSE_ONLY = {"NGROK_AUTHTOKEN"}


def _allowlist() -> set[str]:
    block = re.search(r"APP_CONTAINER_ENV_NAMES\s*=\s*\[(.*?)\]", WORKER, re.DOTALL)
    assert block, "APP_CONTAINER_ENV_NAMES array not found in app-worker.ts"
    return set(re.findall(r'"([A-Z0-9_]+)"', block.group(1)))


def _env_interface_fields() -> set[str]:
    block = re.search(r"interface Env \{(.*?)\}", WORKER, re.DOTALL)
    assert block, "Env interface not found in app-worker.ts"
    return set(re.findall(r"^\s*([A-Z0-9_]+)\?:", block.group(1), re.MULTILINE))


def _documented_env_names() -> set[str]:
    """Uncommented variable names in .env.example."""
    return set(re.findall(r"^([A-Z0-9_]+)=", ENV_EXAMPLE, re.MULTILINE))


def test_every_documented_app_var_is_forwarded_to_the_container() -> None:
    missing = (_documented_env_names() - _COMPOSE_ONLY) - _allowlist()
    assert missing == set(), (
        f"Documented in .env.example but never forwarded by app-worker.ts: {sorted(missing)}. "
        "Add them to APP_CONTAINER_ENV_NAMES (and the Env interface) or, if compose-only, "
        "to _COMPOSE_ONLY here with a rationale."
    )


def test_every_forwarded_name_is_declared_on_the_env_interface() -> None:
    undeclared = _allowlist() - _env_interface_fields()
    assert undeclared == set(), (
        f"In APP_CONTAINER_ENV_NAMES but missing from the Env interface: {sorted(undeclared)}"
    )


def test_every_forwarded_name_is_documented_in_env_example() -> None:
    # Commented-out optionals (e.g. CF_EMAIL_API_URL) count as documented.
    undocumented = {name for name in _allowlist() if name not in ENV_EXAMPLE}
    assert undocumented == set(), (
        f"Forwarded by app-worker.ts but absent from .env.example: {sorted(undocumented)}"
    )


def test_upload_token_secret_reaches_the_hosted_container() -> None:
    # Named as a required `wrangler secret put` in wrangler.app.toml's secrets
    # note; reserved for the signed-token scheme — must be forwarded when set.
    assert "UPLOAD_TOKEN_SECRET" in _allowlist()


def test_voice_provider_credentials_reach_the_hosted_container() -> None:
    # The worker forwards Twilio creds (hosted phone channel is intended), so
    # the STT/TTS provider credentials phone calls need must travel with them.
    required = {
        "STT_PROVIDER",
        "DEEPGRAM_API_KEY",
        "VOICE_LLM_MODEL",
        "TTS_PROVIDER",
        "CARTESIA_API_KEY",
        "CARTESIA_VOICE_ID",
    }
    missing = required - _allowlist()
    assert missing == set(), f"Voice provider vars not forwarded: {sorted(missing)}"
