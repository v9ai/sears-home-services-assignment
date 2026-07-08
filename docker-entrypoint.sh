#!/usr/bin/env bash
# App container entrypoint: fresh DB -> migrate -> seed -> serve
# (mission non-negotiable 3: `docker compose up` must always produce a working system).
#
# Stub-seam note (COORDINATION.md §4): `alembic/versions/` and `app/db/seed.py` land
# with voice-diagnostic-core / technician-scheduling. Until those merge, migrate is a
# no-op (no revisions yet) and seed is skipped gracefully — this script is forward
# compatible with the real migrations/seed once they land, no changes needed here.
set -euo pipefail

echo "[entrypoint] running migrations (alembic upgrade heads)..."
if ! alembic upgrade heads; then
    echo "[entrypoint] alembic upgrade failed" >&2
    exit 1
fi

if python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('app.db.seed') else 1)" 2>/dev/null; then
    echo "[entrypoint] running seed (python -m app.db.seed)..."
    python -m app.db.seed
else
    echo "[entrypoint] app.db.seed not present yet (lands with technician-scheduling) — skipping seed"
fi

echo "[entrypoint] starting: $*"
exec "$@"
