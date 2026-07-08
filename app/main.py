"""FastAPI application entrypoint.

The foundation ships only the health probe. Feature agents mount their own routers
(``/ws/call``, ``/twilio/voice``, upload routes, …) from their owned packages.
"""

import os

from fastapi import FastAPI

from app.phone import phone_router
from app.recordings.routes import router as recordings_router
from app.uploads.routes import router as upload_router
from app.ws.routes import router as ws_router

app = FastAPI(title="Sears Home Services Voice Agent")

app.include_router(ws_router)
app.include_router(upload_router)
app.include_router(phone_router)

# O10 (latency-engineering): in-container latency probes, flag-gated read-only.
if os.environ.get("LATENCY_PROBE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
    from app.latency_probe import router as latency_probe_router

    app.include_router(latency_probe_router)
app.include_router(recordings_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
