#!/usr/bin/env bash
# Fresh-clone rehearsal (mission non-negotiable 3 + this feature's gate):
#   clone this repo to a scratch dir -> cp .env.example .env -> docker compose up
#   -> assert /healthz 200 -> (once landed) seeded technician count -> one
#   scripted text-mode booking round-trip.
#
# Run from the repo root: ./scripts/fresh_clone_smoke.sh
#
# Stub-seam note (COORDINATION.md §4): the technician-seed and booking-round-trip
# checks below SKIP with a warning (not a failure) until technician-scheduling and
# voice-diagnostic-core land their real code — this script does not block on
# features that haven't merged yet, but is written so those checks activate with
# zero changes to this file once the app has a seed table and a /ws/call agent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$(mktemp -d /tmp/sears-fresh-clone-smoke.XXXXXX)"
COMPOSE="docker compose"
FAILED=0

cleanup() {
    echo "[smoke] tearing down..."
    (cd "$WORKDIR/repo" 2>/dev/null && $COMPOSE down -v --remove-orphans) || true
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

echo "[smoke] cloning $REPO_ROOT -> $WORKDIR/repo"
git clone --quiet --no-hardlinks "$REPO_ROOT" "$WORKDIR/repo"
cd "$WORKDIR/repo"

echo "[smoke] cp .env.example .env"
cp .env.example .env
# Smoke-safe placeholders: nothing the foundation skeleton exercises today calls
# OpenAI/Twilio, so the .env.example placeholders are fine as-is. Override here if a
# later pass needs a real OPENAI_API_KEY for a live agent turn.

echo "[smoke] docker compose up --build -d"
$COMPOSE up --build -d

echo "[smoke] waiting for db/app/web to report healthy..."
for _ in $(seq 1 60); do
    STATES=$($COMPOSE ps --format '{{.Service}} {{.Health}}' 2>/dev/null || true)
    if echo "$STATES" | grep -q '^db .*healthy' \
        && echo "$STATES" | grep -q '^app .*healthy' \
        && echo "$STATES" | grep -q '^web .*healthy'; then
        echo "[smoke] all services healthy"
        break
    fi
    sleep 2
done
$COMPOSE ps

echo "[smoke] GET /healthz"
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/healthz || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "[smoke] PASS: /healthz -> 200"
else
    echo "[smoke] FAIL: /healthz -> $HTTP_CODE"
    FAILED=1
fi

echo "[smoke] GET backend-served upload page (/upload/{token})"
UPLOAD_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/upload/smoke-token || echo "000")
if [ "$UPLOAD_CODE" = "200" ]; then
    echo "[smoke] PASS: /upload/smoke-token -> 200"
else
    echo "[smoke] FAIL: /upload/smoke-token -> $UPLOAD_CODE"
    FAILED=1
fi

echo "[smoke] seeded technician count"
TECH_COUNT=$($COMPOSE exec -T db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-sears}" \
    -tAc "SELECT count(*) FROM technicians;" 2>/dev/null || echo "")
if [ -z "$TECH_COUNT" ]; then
    echo "[smoke] SKIP: technicians table not present yet (lands with technician-scheduling)"
elif [ "$TECH_COUNT" -gt 0 ]; then
    echo "[smoke] PASS: $TECH_COUNT seeded technicians"
else
    echo "[smoke] FAIL: technicians table present but empty"
    FAILED=1
fi

echo "[smoke] scripted text-mode booking round-trip (transcript gate, fixture mode)"
if [ -f "scripts/transcript_runner.py" ]; then
    # The runner has no per-scenario flag; fixture mode (default) runs the whole
    # matrix — booking scenarios included — offline and deterministically. It needs
    # the repo's Python deps, which live in the ORIGINATING checkout's .venv (the
    # scratch clone has none); fall back to bare python3 for CI images that
    # pre-install requirements.txt.
    PYTHON_BIN="python3"
    [ -x "$REPO_ROOT/.venv/bin/python" ] && PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
    echo "[smoke] delegating to scripts/transcript_runner.py via $PYTHON_BIN"
    if ! "$PYTHON_BIN" scripts/transcript_runner.py 2>&1; then
        echo "[smoke] FAIL: booking round-trip (transcript gate)"
        FAILED=1
    fi
else
    echo "[smoke] SKIP: scripts/transcript_runner.py not present yet (lands with testing-evals)"
fi

if [ "$FAILED" -ne 0 ]; then
    echo "[smoke] RESULT: FAIL"
    exit 1
fi
echo "[smoke] RESULT: PASS (see SKIP lines above for checks pending later phases)"
